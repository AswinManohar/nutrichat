from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime
from typing import Any

import logfire
from kombu.exceptions import OperationalError

from backend.agent.coaching.handler import handle_coaching
from backend.agent.meal_logging.card import card_fields
from backend.agent.meal_logging.handler import graph_for, handle_meal_logging
from backend.agent.memory import readback
from backend.agent.memory.curator import TurnExtraction, extract_turn
from backend.agent.routing.router import RouteDecision, route_message
from backend.agent.routing.system_one import judge_message
from backend.agent.turn import turn_response
from backend.config import get_tunables
from backend.db.redis_client import CoachingTurn, append_coaching_turns
from backend.quota import UPGRADE_MSG
from backend.safety import profile
from backend.safety.escalation import record_escalation
from backend.safety.red_flags import RedFlagsUnavailable, fallback_text, screen
from backend.safety.tables import TablesUnavailable, load_tables
from backend.workers.tasks import extract_and_store_facts

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()


async def handle_message(
    user_id: str,
    user_input: str,
    thread_id: str,
    checkpointer: Any,
    image_b64: str | None = None,
    meal_type: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    """Route a user message to the meal-logging graph or the coaching agent.

    A paused meal-logging graph always takes priority (never reclassify
    mid-confirmation). An attached image always means meal logging.
    Otherwise the message is routed by ``route_message``. The GLiDE judgment is
    started before the checkpoint read so the two overlap, and it is
    cancelled unread when the turn turns out to be a card reply.

    Args:
        user_id: Supabase Auth UUID.
        user_input: Raw text from the user.
        thread_id: LangGraph thread ID (defaults to user_id in Phase 1).
        checkpointer: AsyncPostgresSaver instance from app.state.
        image_b64: Optional base64-encoded image string.
        meal_type: User-picked meal category sent with a confirm/correct
            action. Injected into graph state on resume so the logged meal
            is filed under the right category.

    Returns:
        Dict with status, message, paused, and items.
    """
    with logfire.span(
        "handle_message",
        user_id=user_id,
        thread_id=thread_id,
        has_image=bool(image_b64),
    ) as span:
        # Before the judgment task, the checkpoint read and any model call
        # (spec 013 FR-015): a paused meal card is left untouched.
        safety_result = await _screen_red_flags(user_id, thread_id, user_input)
        if safety_result is not None:
            span.set_attribute("intent", "safety")
            return safety_result

        graph = graph_for(checkpointer)
        config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

        judgment_task = (
            asyncio.create_task(judge_message(user_input))
            if not image_b64 and user_input.strip()
            else None
        )
        # A patient may be answering a hard-fact readback (spec 013 US4). The
        # profile read overlaps the checkpoint read and the judgment.
        entries_task = (
            asyncio.create_task(_load_entries(user_id))
            if judgment_task is not None and action is None
            else None
        )
        try:
            current_state = await graph.aget_state(config)
            entries = await entries_task if entries_task is not None else []
        except BaseException:
            await _discard(judgment_task)
            await _discard(entries_task)
            raise
        is_paused = bool(current_state.next)

        awaiting = readback.awaiting_reply(entries, thread_id)
        answer = readback.reply_kind(user_input) if awaiting else "other"
        readback_takes = (
            answer != "other"
            and not image_b64
            and (not is_paused or _readback_is_newer(current_state, awaiting))
        )

        extraction: TurnExtraction | None = None
        if readback_takes and answer == "correction":
            # "No, it's prawns": only a reply that states the same kind of
            # fact again is a correction; "no carb ideas please" is not.
            extraction = await _read_correction(user_id, user_input, awaiting)
            readback_takes = extraction is not None

        decision: RouteDecision | None = None
        is_coaching = False
        reply_handled = False
        if readback_takes:
            await _discard(judgment_task)
            result = await _answer_readback(
                user_id, thread_id, awaiting, answer, current_state, extraction
            )
            reply_handled = True
        else:
            if is_paused or image_b64:
                await _discard(judgment_task)
            else:
                decision = await route_message(user_input, judgment_task)
            is_coaching = decision is not None and decision.intent == "coaching"
            if is_coaching:
                result = await handle_coaching(
                    user_id,
                    user_input,
                    conversation_id=thread_id,
                    offer_to_log=decision.offer_to_log,
                    routing=decision.routing_record(),
                )
            else:
                result = await handle_meal_logging(
                    graph,
                    config,
                    user_input,
                    user_id,
                    image_b64,
                    is_paused,
                    meal_type,
                    action,
                )
                if awaiting and is_paused and answer != "other":
                    # The card took this reply; say the question is still open.
                    result = _note_waiting_readback(result, awaiting)

        span.set_attribute(
            "intent",
            "readback" if reply_handled else "coaching" if is_coaching else "log_meal",
        )
        span.set_attribute("paused", result["paused"])

    # Short-term coaching memory: both intents, so the coach knows what was
    # just logged as well as what was just asked.
    await _record_turn(user_id, user_input, image_b64, result)
    # Preference memory (PRD F6): fire-and-forget after the reply. Card
    # button presses and photo-only turns carry no statement to learn from,
    # so they skip the task (and its LLM call) entirely.
    # A coaching turn that extracted facts in the turn, and a readback answer
    # (which read its own correction), need no second pass.
    facts_extracted = bool(result.pop("facts_extracted", False)) or reply_handled
    if action is None and user_input.strip() and not facts_extracted:
        _enqueue_fact_extraction(user_id, user_input, result["message"])
    return result


async def _load_entries(user_id: str) -> list[profile.HardEntry]:
    """The patient's live hard entries; empty (and logged) when unreadable.

    Only used to spot a readback answer: if the read fails the message is
    routed as a normal turn, and the coaching path fails closed on its own.
    """
    try:
        return await profile.load_hard_profile(user_id)
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("could not read the hard profile for %s: %s", user_id, exc)
        return []


def _readback_is_newer(state: Any, awaiting: list[profile.HardEntry]) -> bool:
    """Whether the readback was asked after the paused meal card was made.

    Whichever was asked last takes the reply. A checkpoint without a readable
    timestamp keeps the card, which is the behaviour before readbacks existed.
    """
    created = getattr(state, "created_at", None)
    asked = awaiting[0].readback_asked_at
    try:
        card_at = datetime.fromisoformat(created) if created else None
    except (TypeError, ValueError):
        card_at = None
    return card_at is not None and asked is not None and asked > card_at


def _question_text(awaiting: list[profile.HardEntry]) -> str:
    """The readback sentences for ``awaiting``; empty when tables are down."""
    try:
        tables = load_tables()
    except TablesUnavailable as exc:
        logger.error("clinical tables unavailable, readback text dropped: %s", exc)
        return ""
    return " ".join(readback.sentence(e, tables) for e in awaiting)


def _note_waiting_readback(
    result: dict[str, Any], awaiting: list[profile.HardEntry]
) -> dict[str, Any]:
    """Append "still waiting for your answer on this: ..." to a card reply."""
    question = _question_text(awaiting)
    if not question:
        return result
    note = _TUNABLES.memory.readback_still_waiting_text.format(question=question)
    return {**result, "message": f"{result['message']}\n\n{note}"}


async def _answer_readback(
    user_id: str,
    thread_id: str,
    awaiting: list[profile.HardEntry],
    answer: str,
    state: Any,
    extraction: TurnExtraction | None,
) -> dict[str, Any]:
    """Apply a yes / no / correction to the readback asked last.

    A yes or a plain no is one database write and no model call. A correction
    ("no, it's prawns") arrives with the extraction of its new fact already
    written; the reply asks about it. The reply names the open meal card.
    """
    with logfire.span("readback_reply", answer=answer):
        text = await readback.apply_reply(user_id, awaiting, answer)
        response: dict[str, Any] = {
            "status": "success",
            "message": text,
            "paused": False,
            "items": [],
        }
        if extraction is not None and extraction.changed_hard:
            response = await _read_back_new(user_id, thread_id, response)
    if state.next:
        values = state.values
        response["message"] = (
            f"{response['message']}\n\n{_TUNABLES.memory.card_waiting_text}"
        )
        response["paused"] = True
        response.update(await card_fields(user_id, values, response["message"]))
    return response


async def _read_correction(
    user_id: str, user_input: str, awaiting: list[profile.HardEntry]
) -> TurnExtraction | None:
    """Whether a "no ..." message corrects what was asked, and what it states.

    A no to a retirement request is always an answer (the entry keeps
    binding). Otherwise the message is read for hard facts, and it counts as
    a correction only when one of them has the same type as an entry asked
    about. The facts are written either way (they are the patient's words).

    Returns:
        The extraction when it is a correction; None when the message is
        something else and should be routed normally.
    """
    if all(e.state == "confirmed" for e in awaiting):
        return TurnExtraction()
    try:
        extraction = await extract_turn(user_id, user_input)
    except Exception as exc:  # noqa: BLE001 — route the message normally instead
        logger.error("could not read the correction for %s: %s", user_id, exc)
        return None
    asked_types = {e.type for e in awaiting if e.state == "pending"}
    stated = [*extraction.asked, *extraction.accepted]
    return extraction if any(e.type in asked_types for e in stated) else None


async def _read_back_new(
    user_id: str, thread_id: str, response: dict[str, Any]
) -> dict[str, Any]:
    """Ask about the facts a correction just wrote; log and skip on failure."""
    try:
        entries = await profile.load_hard_profile(user_id)
        planned = readback.plan_readback(entries, thread_id, load_tables())
        await readback.commit_readback(user_id, planned, thread_id)
    except Exception as exc:  # noqa: BLE001 — the denial itself already happened
        logger.error("could not read back the correction for %s: %s", user_id, exc)
        return response
    if planned.empty:
        return response
    response["message"] = f"{response['message']}\n\n{planned.text}"
    if planned.readback is not None:
        response["readback"] = planned.readback.model_dump()
    return response


def _safety_result(message: str) -> dict[str, Any]:
    """Fixed-reply response shape; the client renders it as a safety message."""
    return turn_response(message, kind="safety")


async def _screen_red_flags(
    user_id: str, thread_id: str, user_input: str
) -> dict[str, Any] | None:
    """Screen the text; return the fixed reply on a match or an unreadable list.

    The message is not recorded into coaching history and no fact extraction
    is queued, so the model never sees it later. Spans carry the rule id and
    duration only, never the text.
    """
    if not user_input.strip():
        return None
    with logfire.span("red_flag_screen") as span:
        started = time.perf_counter()
        try:
            match = screen(user_input)
        except RedFlagsUnavailable as exc:
            span.set_attribute("rule_id", "unavailable")
            logfire.error(
                "red-flag list unavailable: refusing model replies",
                user_id=user_id,
                error=str(exc),
            )
            return _safety_result(fallback_text())
        finally:
            span.set_attribute("duration_ms", (time.perf_counter() - started) * 1000)
        span.set_attribute("rule_id", match.rule_id if match else "none")
    if match is None:
        return None
    await record_escalation(user_id, thread_id, user_input, match)
    return _safety_result(match.response)


async def _discard(task: asyncio.Task[Any] | None) -> None:
    """Cancel a judgment the turn no longer needs and wait for it to finish."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _summarize_logging_result(result: dict[str, Any]) -> str:
    """One-line assistant-side summary of a meal-logging turn for history.

    A pending confirmation card is condensed to its items and totals (the
    rendered card is long and half of it is UI chrome). Anything else — the
    post-log reply, a cancel, an error — is already short and is kept as-is.
    """
    items = result.get("items") or []
    if not (result.get("paused") and items):
        return result["message"]
    foods = ", ".join(f"{i['food_name']} {i['qty_g']:g}g" for i in items)
    kcal = sum(i["kcal"] for i in items)
    protein = sum(i["protein_g"] for i in items)
    return (
        f"Proposed a meal card, awaiting confirmation: {foods} "
        f"(~{kcal:.0f} kcal, {protein:.0f}g protein)."
    )


async def _record_turn(
    user_id: str,
    user_input: str,
    image_b64: str | None,
    result: dict[str, Any],
) -> None:
    """Append this exchange to the user's coaching history.

    Never raises: history is a side effect of the turn, and the reply has
    already been produced by the time this runs.
    """
    if result["message"] == UPGRADE_MSG:
        return
    user_text = user_input.strip() or ("[sent a meal photo]" if image_b64 else "")
    if not user_text:
        return
    turns = [
        CoachingTurn(role="user", content=user_text),
        CoachingTurn(role="assistant", content=_summarize_logging_result(result)),
    ]
    try:
        await append_coaching_turns(user_id, turns)
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("coaching history append failed for %s: %s", user_id, exc)


def _enqueue_fact_extraction(user_id: str, user_input: str, agent_reply: str) -> None:
    """Enqueue preference-fact extraction; a broker outage never blocks the reply.

    Args:
        user_id: Supabase Auth UUID.
        user_input: The user's message this turn.
        agent_reply: The agent's response this turn.
    """
    try:
        extract_and_store_facts.delay(user_id, user_input, agent_reply)
    except (OperationalError, OSError) as exc:
        logger.warning("Could not enqueue fact extraction: %s", exc)
