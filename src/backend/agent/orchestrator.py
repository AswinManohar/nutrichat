from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Literal

import logfire
from kombu.exceptions import OperationalError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

from backend.agent.coaching import CoachingAgent
from backend.agent.coaching_store import save_coaching_response
from backend.agent.graph import build_graph
from backend.agent.llm import COACHING_MODEL, FLASH_LITE_MODEL, make_llm
from backend.agent.system_one import RoutingJudgment, judge_message
from backend.agent.tools.usda import NULLABLE_MACROS
from backend.config import get_tunables
from backend.db.redis_client import CoachingTurn, append_coaching_turns
from backend.quota import UPGRADE_MSG, consume_llm_credit
from backend.workers.tasks import extract_and_store_facts

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

_INTENT_SYSTEM = _TUNABLES.prompts.intent_system

RoutePath = Literal["judgment", "second_opinion_unsure", "second_opinion_unavailable"]


class _IntentResult(BaseModel):
    type: Literal["log_meal", "coaching"]

    model_config = ConfigDict(extra="forbid")


class RouteDecision(BaseModel):
    """How one fresh message was routed (see specs/001-jev-intent-routing)."""

    intent: Literal["log_meal", "coaching"]
    path: RoutePath
    judgment: RoutingJudgment | None
    offer_to_log: bool

    model_config = ConfigDict(extra="forbid")

    def routing_record(self) -> dict[str, float | str | bool] | None:
        """Values stored in coaching_response.parsed_query["routing"].

        None when Jev gave no answer, so there is nothing to compare with
        Gemini's needs_guidance (spec Story 5, scenario 4).
        """
        if self.judgment is None:
            return None
        return {
            "path": self.path,
            "certainty": round(self.judgment.certainty, 4),
            "raw_choice": self.judgment.raw_choice,
            "reports_food": round(self.judgment.reports_food, 4),
            "needs_guidance_jev": round(self.judgment.needs_guidance, 4),
            "offer_to_log": self.offer_to_log,
        }


# Gemini flash-lite spends thinking tokens from this same budget before the
# structured JSON — too low a limit truncates output (see tunables.yaml).
_intent_llm = make_llm(
    FLASH_LITE_MODEL,
    max_output_tokens=_TUNABLES.token_limits.intent_classifier_max_output,
).with_structured_output(_IntentResult)
_coaching_agent = CoachingAgent()

# Compiling the StateGraph is pure CPU work with no per-message state, so do it
# once per checkpointer instead of on every turn. Keyed by checkpointer identity:
# in production the checkpointer is a process-lifetime singleton (held by
# app.state), so this compiles the graph exactly once. A None checkpointer (unit
# tests, no-persistence callers) always rebuilds, keeping patched build_graph
# isolated per test.
_compiled_graphs: dict[int, Any] = {}


def _graph_for(checkpointer: Any) -> Any:
    """Return a compiled graph for this checkpointer, building it at most once."""
    if checkpointer is None:
        return build_graph(checkpointer)
    key = id(checkpointer)
    graph = _compiled_graphs.get(key)
    if graph is None:
        graph = build_graph(checkpointer)
        _compiled_graphs[key] = graph
    return graph


async def _classify_with_gemini(message: str) -> Literal["log_meal", "coaching"]:
    """Second opinion: the Gemini intent classifier. Never costs a usage credit."""
    with logfire.span("classify_intent_llm"):
        result = await _intent_llm.ainvoke(
            [
                SystemMessage(content=_INTENT_SYSTEM),
                HumanMessage(content=message),
            ]
        )
    return result.type


async def _route(
    message: str,
    judgment_task: (
        asyncio.Task[tuple[RoutingJudgment | None, str | None]] | None
    ) = None,
) -> RouteDecision:
    """Decide which handler a fresh message goes to.

    Jev's judgment is the single routing path. A judgment at or above
    ``typesafe.intent_min_probability`` is acted on directly; below it, or
    when Jev gave no answer, the Gemini classifier decides. No path spends a
    usage credit or looks at the user's balance; credits are spent only by
    the handler that does the requested work.

    Args:
        message: Raw user message.
        judgment_task: A ``judge_message`` task already started by the caller
            (so it overlaps other I/O). None starts no judgment, and Gemini
            decides.

    Returns:
        The route, which path decided it, and whether a coaching reply should
        end with the offer to log.
    """
    cfg = _TUNABLES.typesafe
    with logfire.span("route_message") as span:
        if judgment_task is None:
            judgment, failure = None, "not_requested"
        else:
            judgment, failure = await judgment_task

        path: RoutePath
        if judgment is None:
            path = "second_opinion_unavailable"
            intent = await _classify_with_gemini(message)
        elif judgment.certainty >= cfg.intent_min_probability:
            path = "judgment"
            intent = judgment.intent
        else:
            path = "second_opinion_unsure"
            intent = await _classify_with_gemini(message)

        decision = RouteDecision(
            intent=intent,
            path=path,
            judgment=judgment,
            offer_to_log=(
                intent == "coaching"
                and judgment is not None
                and judgment.reports_food >= cfg.log_offer_min_probability
            ),
        )
        span.set_attribute("path", path)
        span.set_attribute("intent", intent)
        span.set_attribute("offer_to_log", decision.offer_to_log)
        if failure is not None:
            span.set_attribute("failure", failure)
        if judgment is not None:
            span.set_attribute("certainty", judgment.certainty)
            span.set_attribute("raw_choice", judgment.raw_choice)
            span.set_attribute("reports_food", judgment.reports_food)
            span.set_attribute("needs_guidance_jev", judgment.needs_guidance)
            span.set_attribute("judgment_ms", judgment.latency_ms)
    return decision


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
    Otherwise the message is routed by ``_route``. The Jev judgment is
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
        graph = _graph_for(checkpointer)
        config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

        judgment_task = (
            asyncio.create_task(judge_message(user_input))
            if not image_b64 and user_input.strip()
            else None
        )
        try:
            current_state = await graph.aget_state(config)
        except BaseException:
            await _discard(judgment_task)
            raise
        is_paused = bool(current_state.next)

        decision: RouteDecision | None = None
        if is_paused or image_b64:
            await _discard(judgment_task)
        else:
            decision = await _route(user_input, judgment_task)
        is_coaching = decision is not None and decision.intent == "coaching"
        if is_coaching:
            result = await _handle_coaching(
                user_id,
                user_input,
                conversation_id=thread_id,
                offer_to_log=decision.offer_to_log,
                routing=decision.routing_record(),
            )
        else:
            result = await _handle_meal_logging(
                graph,
                config,
                user_input,
                user_id,
                image_b64,
                is_paused,
                meal_type,
                action,
            )

        span.set_attribute("intent", "coaching" if is_coaching else "log_meal")
        span.set_attribute("paused", result["paused"])

    # Short-term coaching memory: both intents, so the coach knows what was
    # just logged as well as what was just asked.
    await _record_turn(user_id, user_input, image_b64, result)
    # Preference memory (PRD F6): fire-and-forget on every handled turn.
    _enqueue_fact_extraction(user_id, user_input, result["message"])
    return result


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


def _serialize_items(usda_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape raw USDA lookup results into the confirmation-card item format.

    Shared by the normal paused meal-logging response and the
    `GET /meals/pending` recovery path so the two shapes can never drift.

    Args:
        usda_results: Raw entries from graph state, keyed by food_name,
            qty_g, match_confidence, kcal, protein_g, carbs_g, fat_g,
            fiber_g, fdc_id, and optional extras.

    Returns:
        List of dicts shaped for the frontend confirmation card.
    """
    items = []
    for r in usda_results:
        # Released clients parse protein/carbs/fat/fiber as required numbers, so
        # an unknown (None) goes out as 0.0 *and* is named in
        # `unknown_nutrients` (the source of truth for "not reported by FDC").
        # sugar_g / sat_fat_g are optional on every client and stay null.
        unknown = [m for m in NULLABLE_MACROS if r.get(m) is None and m in r]
        items.append(
            {
                "food_name": r["food_name"],
                "qty_g": r["qty_g"],
                "confidence": r["match_confidence"],
                "kcal": r["kcal"],
                "protein_g": r["protein_g"] if r["protein_g"] is not None else 0.0,
                "carbs_g": r["carbs_g"] if r["carbs_g"] is not None else 0.0,
                "fat_g": r["fat_g"] if r["fat_g"] is not None else 0.0,
                "fiber_g": r["fiber_g"] if r["fiber_g"] is not None else 0.0,
                "fdc_id": r["fdc_id"],
                "candidates": r.get("candidates", []),
                "candidate_details": r.get("candidate_details", []),
                "source": r.get("source", "USDA"),
                "estimated": r.get("estimated", False),
                "source_dish": r.get("source_dish"),
                "is_composite": r.get("is_composite", False),
                # Spec 003 research R9: the user's original words, when not
                # already derivable from food_name (picker prefill).
                "input_phrase": r.get("input_phrase"),
                # Optional on every client. Micronutrients are not part of the
                # card (spec 008 FR-014): the server re-derives them at log /
                # save time, so no `nutrients` / `micros` payload is sent.
                "sugar_g": r.get("sugar_g"),
                "sat_fat_g": r.get("sat_fat_g"),
                "unknown_nutrients": unknown,
            }
        )
    return items


def _saved_meal_payload(values: dict[str, Any]) -> dict[str, str] | None:
    """Build the `saved_meal` response field from graph state values.

    Uses `.get()` so threads checkpointed before the field existed read as
    "not from a saved meal".

    Returns:
        `{"id", "name", "updated_at"}` when the card came from a saved meal,
        else None.
    """
    saved_id = values.get("saved_meal_id")
    if not saved_id:
        return None
    return {
        "id": saved_id,
        "name": values.get("saved_meal_name") or "",
        "updated_at": values.get("saved_meal_updated_at") or "",
    }


async def get_pending_card(
    user_id: str,
    thread_id: str,
    checkpointer: Any,
) -> dict[str, Any]:
    """Return the unanswered confirmation card for a thread, if any.

    Read-only recovery path for clients that lost the POST /meals/log
    response (mobile process death, dropped connection). Never runs the
    graph, never consumes quota.

    Args:
        user_id: Supabase Auth UUID.
        thread_id: LangGraph thread ID.
        checkpointer: AsyncPostgresSaver instance from app.state.

    Returns:
        `{"paused": False}` when no interrupt is pending, otherwise
        `{"status": "pending", "paused": True, "message": ..., "items": ...}`.
    """
    graph = _graph_for(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    state = await graph.aget_state(config)
    if not state.next or state.values.get("resolved"):
        return {"paused": False}
    messages = state.values.get("messages", [])
    ai_texts = [m.content for m in messages if getattr(m, "type", "") == "ai"]
    return {
        "status": "pending",
        "paused": True,
        "message": ai_texts[-1] if ai_texts else "",
        "items": _serialize_items(state.values.get("usda_results", [])),
        "saved_meal": _saved_meal_payload(state.values),
    }


async def resolve_pending(
    user_id: str,
    thread_id: str,
    checkpointer: Any,
) -> None:
    """Mark a paused thread's confirmation card resolved (spec 003, T008).

    Called from `POST /meals/log-items` after a client-side local swap/edit
    flow logs a meal directly (no LLM round trip), so the LangGraph
    checkpoint that produced the original card never learns the card was
    handled. Without this, `get_pending_card` would keep returning the
    stale, unswapped card on the next pending-recovery poll (research R4).

    This never deletes checkpoint rows (rule U1) -- it writes one more
    checkpoint on top with `resolved=True`, which `get_pending_card` checks.
    The full history therefore stays intact for debugging/audit.

    Idempotent and a no-op if nothing is paused for this thread.

    Args:
        user_id: Supabase Auth UUID.
        thread_id: LangGraph thread ID (`{user_id}:{conversation_id}`).
        checkpointer: AsyncPostgresSaver instance from app.state.
    """
    graph = _graph_for(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    state = await graph.aget_state(config)
    if not state.next or state.values.get("resolved"):
        return
    await graph.aupdate_state(config, {"resolved": True}, as_node="present")


async def _handle_meal_logging(
    graph: Any,
    config: dict[str, Any],
    user_input: str,
    user_id: str,
    image_b64: str | None,
    is_paused: bool,
    meal_type: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    """Run (or resume) the meal-logging graph and shape its response.

    Args:
        graph: Compiled LangGraph StateGraph.
        config: LangGraph config with thread_id and user_id.
        user_input: Raw text from the user.
        user_id: Supabase Auth UUID.
        image_b64: Optional base64-encoded image string.
        is_paused: Whether the graph was paused at the confirmation interrupt.
        meal_type: User-picked meal category, injected into state on resume.

    Returns:
        Dict with status, message, paused, and items.
    """
    with logfire.span("meal_logging"):
        if is_paused:
            # Resume: inject new message (+ picked category + any card action)
            # into checkpoint state, then resume with None. `action` is set
            # every resume (None unless decomposing) so a stale value can't
            # re-trigger the decompose branch on the next confirm.
            # Paused resumes (correct/decompose/confirm) are exempt from quota —
            # only apply_correction and decompose_to_ingredients are called, which
            # are explicitly excluded from the per-inference count.
            update: dict[str, Any] = {
                "messages": [HumanMessage(content=user_input)],
                "action": action,
            }
            if meal_type is not None:
                update["meal_type"] = meal_type
            await graph.aupdate_state(config, update)
            result = await graph.ainvoke(None, config=config)
        else:
            # Fresh start: consume one credit for the extraction LLM call.
            granted = await consume_llm_credit(user_id)
            if not granted:
                return {
                    "status": "success",
                    "message": UPGRADE_MSG,
                    "paused": False,
                    "items": [],
                }
            result = await graph.ainvoke(
                {
                    "messages": [HumanMessage(content=user_input)],
                    "user_id": user_id,
                    "image_b64": image_b64 or "",
                    "entities": [],
                    "usda_results": [],
                    "meal_type": None,
                    "action": None,
                    "from_saved": False,
                    "saved_meal_id": None,
                    "saved_meal_name": None,
                    "saved_meal_updated_at": None,
                    "meal_id": None,
                    "decomposed_entities": [],
                    "pre_decompose_entities": [],
                    # A new user turn always starts unresolved, even when the
                    # thread was reused after a previous card was logged via
                    # POST /meals/log-items (resolve_pending, T008/T009).
                    # Without this, a leftover resolved=True from that prior
                    # card would make get_pending_card treat THIS turn's new
                    # card as already handled the moment it pauses again.
                    "resolved": False,
                },
                config=config,
            )

        # Check if graph paused again (e.g. after correction loop re-presents card)
        new_state = await graph.aget_state(config)
        still_paused = bool(new_state.next)

        last_ai = next(
            (m for m in reversed(result["messages"]) if isinstance(m, AIMessage)),
            None,
        )

        # Expose structured items so the frontend can render editable quantity
        # fields. Only included when paused (confirmation card shown); empty
        # after log/cancel.
        items = _serialize_items(result.get("usda_results", [])) if still_paused else []

        response: dict[str, Any] = {
            "status": "success",
            "message": last_ai.content if last_ai else "",
            "paused": still_paused,
            "items": items,
        }
        if still_paused:
            response["saved_meal"] = _saved_meal_payload(result)
        else:
            response["meal_id"] = result.get("meal_id")
        return response


async def _handle_coaching(
    user_id: str,
    user_input: str,
    conversation_id: str | None = None,
    offer_to_log: bool = False,
    routing: dict[str, float | str | bool] | None = None,
) -> dict[str, Any]:
    """Answer a nutrition question via the coaching agent.

    Consumes one quota credit per coaching turn (not per internal LLM call
    inside CoachingAgent). Returns an upgrade prompt when over quota.
    Persists the reply to coaching_response so it can be rated and exported;
    a failed write drops ``response_id`` but still returns the reply.

    Args:
        user_id: Supabase Auth UUID.
        user_input: User's nutrition question.
        conversation_id: Thread id from the request, stored with the reply.
        offer_to_log: The message also reported food, so the reply ends with
            ``typesafe.log_offer_text``. Never added to the upgrade message.
        routing: Jev's routing record for this turn, stored beside Gemini's
            parse as ``parsed_query["routing"]``; None when Jev gave no answer.

    Returns:
        Dict with status, message, paused=False, items=[] — same shape as
        meal logging so web and Telegram channels stay uniform — plus
        response_id when the reply was persisted.
    """
    granted = await consume_llm_credit(user_id)
    if not granted:
        return {
            "status": "success",
            "message": UPGRADE_MSG,
            "paused": False,
            "items": [],
        }
    with logfire.span("coaching") as span:
        result = await _coaching_agent.handle(user_id, user_input)
        if offer_to_log:
            # Appended after citations were extracted, so [n] parsing is
            # untouched; saved and remembered with the offer included.
            result = result.model_copy(
                update={
                    "message": (
                        f"{result.message}\n\n{_TUNABLES.typesafe.log_offer_text}"
                    )
                }
            )
        span_ctx = trace.get_current_span().get_span_context()
        trace_id = format(span_ctx.trace_id, "032x") if span_ctx.is_valid else None
        response_id = await save_coaching_response(
            user_id=user_id,
            conversation_id=conversation_id,
            query=user_input,
            result=result,
            model=COACHING_MODEL,
            trace_id=trace_id,
            routing=routing,
        )
        span.set_attribute("needs_guidance", result.parsed.needs_guidance)
        span.set_attribute("retrieved_count", len(result.retrieved))
        span.set_attribute("citation_count", len(result.citations))
        span.set_attribute("response_id", response_id or "")

    response: dict[str, Any] = {
        "status": "success",
        "message": result.message,
        "paused": False,
        "items": [],
    }
    if response_id is not None:
        response["response_id"] = response_id
    return response
