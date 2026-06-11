from __future__ import annotations

import logging
from typing import Any, Literal

from kombu.exceptions import OperationalError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langsmith import traceable
from pydantic import BaseModel, ConfigDict

from backend.agent.coaching import CoachingAgent
from backend.agent.graph import build_graph
from backend.agent.llm import FLASH_LITE_MODEL, make_llm
from backend.config import get_tunables
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


def _trace_inputs(inputs: dict) -> dict:
    """Keep only small, serializable fields in LangSmith trace inputs."""
    keep = ("user_id", "user_input", "thread_id", "message", "is_paused")
    return {k: v for k, v in inputs.items() if k in keep}


@traceable(name="classify_intent", run_type="chain", process_inputs=_trace_inputs)
async def _classify_intent(message: str) -> str:
    """Classify a fresh user message as log_meal or coaching.

    Two-stage: keyword pre-filter (zero LLM cost), LLM fallback when
    ambiguous (per coaching agent design spec §3).

    Args:
        message: Raw user message.

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

    result = await _intent_llm.ainvoke(
        [
            SystemMessage(content=_INTENT_SYSTEM),
            HumanMessage(content=message),
        ]
    )
    return result.type


@traceable(name="handle_message", run_type="chain", process_inputs=_trace_inputs)
async def handle_message(
    user_id: str,
    user_input: str,
    thread_id: str,
    checkpointer: Any,
    image_b64: str | None = None,
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

    Returns:
        Dict with status, message, paused, and items.
    """
    graph = build_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

    current_state = await graph.aget_state(config)
    is_paused = bool(current_state.next)

    if (
        not is_paused
        and not image_b64
        and await _classify_intent(user_input) == "coaching"
    ):
        result = await _handle_coaching(user_id, user_input)
    else:
        result = await _handle_meal_logging(
            graph, config, user_input, user_id, image_b64, is_paused
        )

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


@traceable(name="meal_logging", run_type="chain", process_inputs=_trace_inputs)
async def _handle_meal_logging(
    graph: Any,
    config: dict[str, Any],
    user_input: str,
    user_id: str,
    image_b64: str | None,
    is_paused: bool,
) -> dict[str, Any]:
    """Run (or resume) the meal-logging graph and shape its response.

    Args:
        graph: Compiled LangGraph StateGraph.
        config: LangGraph config with thread_id and user_id.
        user_input: Raw text from the user.
        user_id: Supabase Auth UUID.
        image_b64: Optional base64-encoded image string.
        is_paused: Whether the graph was paused at the confirmation interrupt.

    Returns:
        Dict with status, message, paused, and items.
    """
    if is_paused:
        # Resume: inject new message into checkpoint state, then resume with None
        await graph.aupdate_state(
            config,
            {"messages": [HumanMessage(content=user_input)]},
        )
        result = await graph.ainvoke(None, config=config)
    else:
        # Fresh start: supply full initial state
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "user_id": user_id,
                "image_b64": image_b64 or "",
                "entities": [],
                "usda_results": [],
                "meal_type": None,
            },
            config=config,
        )

    # Check if graph paused again (e.g. after correction loop re-presents card)
    new_state = await graph.aget_state(config)
    still_paused = bool(new_state.next)

    last_ai = next(
        (m for m in reversed(result["messages"]) if isinstance(m, AIMessage)), None
    )

    # Expose structured items so the frontend can render editable quantity fields.
    # Only included when paused (confirmation card shown); empty after log/cancel.
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
                }
            )

    return {
        "status": "success",
        "message": last_ai.content if last_ai else "",
        "paused": still_paused,
        "items": items,
    }


@traceable(name="coaching", run_type="chain", process_inputs=_trace_inputs)
async def _handle_coaching(user_id: str, user_input: str) -> dict[str, Any]:
    """Answer a nutrition question via the coaching agent.

    Args:
        user_id: Supabase Auth UUID.
        user_input: User's nutrition question.

    Returns:
        Dict with status, message, paused=False, and items=[] — same shape
        as meal logging so web and Telegram channels stay uniform.
    """
    message = await _coaching_agent.handle(user_id, user_input)
    return {"status": "success", "message": message, "paused": False, "items": []}
