from __future__ import annotations

import logging
from typing import Any, Literal

import logfire
from kombu.exceptions import OperationalError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from backend.agent.coaching import CoachingAgent
from backend.agent.graph import build_graph
from backend.agent.llm import FLASH_LITE_MODEL, make_llm
from backend.config import get_tunables
from backend.quota import consume_llm_credit
from backend.workers.tasks import extract_and_store_facts

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

_LOG_SIGNALS = frozenset(_TUNABLES.routing.log_signals)
_QUERY_SIGNALS = frozenset(_TUNABLES.routing.query_signals)
_INTENT_SYSTEM = _TUNABLES.prompts.intent_system


class _IntentResult(BaseModel):
    type: Literal["log_meal", "coaching"]

    model_config = ConfigDict(extra="forbid")


# Gemini flash-lite spends thinking tokens from this same budget before the
# structured JSON — too low a limit truncates output (see tunables.yaml).
_intent_llm = make_llm(
    FLASH_LITE_MODEL,
    max_output_tokens=_TUNABLES.token_limits.intent_classifier_max_output,
).with_structured_output(_IntentResult)
_coaching_agent = CoachingAgent()


async def _classify_intent(message: str, user_id: str) -> str:
    """Classify a fresh user message as log_meal or coaching.

    Two-stage: keyword pre-filter (zero LLM cost and zero quota), LLM
    fallback when ambiguous. When over quota, skips the LLM and defaults
    to log_meal.

    Args:
        message: Raw user message.
        user_id: Supabase Auth UUID — used for quota check before LLM call.

    Returns:
        "log_meal" or "coaching".
    """
    lowered = message.lower()
    has_log = any(sig in lowered for sig in _LOG_SIGNALS)
    has_query = any(sig in lowered for sig in _QUERY_SIGNALS)

    if has_query:
        return "coaching"
    if has_log:
        return "log_meal"

    granted = await consume_llm_credit(user_id)
    if not granted:
        return "log_meal"

    with logfire.span("classify_intent_llm"):
        result = await _intent_llm.ainvoke(
            [
                SystemMessage(content=_INTENT_SYSTEM),
                HumanMessage(content=message),
            ]
        )
    return result.type


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
    Otherwise, intent is classified and routed accordingly.

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
        graph = build_graph(checkpointer)
        config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

        current_state = await graph.aget_state(config)
        is_paused = bool(current_state.next)

        is_coaching = (
            not is_paused
            and not image_b64
            and await _classify_intent(user_input, user_id) == "coaching"
        )
        if is_coaching:
            result = await _handle_coaching(user_id, user_input)
        else:
            result = await _handle_meal_logging(
                graph, config, user_input, user_id, image_b64, is_paused, meal_type, action
            )

        span.set_attribute("intent", "coaching" if is_coaching else "log_meal")
        span.set_attribute("paused", result["paused"])

    # Preference memory (PRD F6): fire-and-forget on every handled turn.
    _enqueue_fact_extraction(user_id, user_input, result["message"])
    return result


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
                    "message": _UPGRADE_MSG,
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
                    "meal_id": None,
                    "decomposed_entities": [],
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
        items = []
        if still_paused:
            for r in result.get("usda_results", []):
                items.append(
                    {
                        "food_name": r["food_name"],
                        "qty_g": r["qty_g"],
                        "confidence": r["match_confidence"],
                        "kcal": r["kcal"],
                        "protein_g": r["protein_g"],
                        "carbs_g": r["carbs_g"],
                        "fat_g": r["fat_g"],
                        "fiber_g": r["fiber_g"],
                        "fdc_id": r["fdc_id"],
                        "candidates": r.get("candidates", []),
                        "source": r.get("source", "USDA"),
                        "estimated": r.get("estimated", False),
                        "source_dish": r.get("source_dish"),
                        # Full breakdown so "Save to My Meals" preserves micros.
                        "sugar_g": r.get("sugar_g", 0.0),
                        "sat_fat_g": r.get("sat_fat_g", 0.0),
                        "nutrients": r.get("nutrients", {}),
                    }
                )

        response: dict[str, Any] = {
            "status": "success",
            "message": last_ai.content if last_ai else "",
            "paused": still_paused,
            "items": items,
        }
        if not still_paused:
            response["meal_id"] = result.get("meal_id")
        return response


_UPGRADE_MSG = (
    "You've used all your free AI requests. "
    "Visit nutrichat.app/upgrade to continue."
)


async def _handle_coaching(user_id: str, user_input: str) -> dict[str, Any]:
    """Answer a nutrition question via the coaching agent.

    Consumes one quota credit per coaching turn (not per internal LLM call
    inside CoachingAgent). Returns an upgrade prompt when over quota.

    Args:
        user_id: Supabase Auth UUID.
        user_input: User's nutrition question.

    Returns:
        Dict with status, message, paused=False, and items=[] — same shape
        as meal logging so web and Telegram channels stay uniform.
    """
    granted = await consume_llm_credit(user_id)
    if not granted:
        return {"status": "success", "message": _UPGRADE_MSG, "paused": False, "items": []}
    with logfire.span("coaching"):
        message = await _coaching_agent.handle(user_id, user_input)
    return {"status": "success", "message": message, "paused": False, "items": []}
