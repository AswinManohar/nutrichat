"""Meal-logging turn handling: the compiled graph, the pending card, one turn."""

from __future__ import annotations

import json
from typing import Any

import logfire
from langchain_core.messages import AIMessage, HumanMessage

from backend.agent.llm import FLASH_LITE_MODEL
from backend.agent.meal_logging.card import card_fields
from backend.agent.meal_logging.graph import build_graph
from backend.quota import UPGRADE_MSG, consume_llm_credit

# Compiling the StateGraph is pure CPU work with no per-message state, so do it
# once per checkpointer instead of on every turn. Keyed by checkpointer identity:
# in production the checkpointer is a process-lifetime singleton (held by
# app.state), so this compiles the graph exactly once. A None checkpointer (unit
# tests, no-persistence callers) always rebuilds, keeping patched build_graph
# isolated per test.
_compiled_graphs: dict[int, Any] = {}


def graph_for(checkpointer: Any) -> Any:
    """Return a compiled graph for this checkpointer, building it at most once."""
    if checkpointer is None:
        return build_graph(checkpointer)
    key = id(checkpointer)
    graph = _compiled_graphs.get(key)
    if graph is None:
        graph = build_graph(checkpointer)
        _compiled_graphs[key] = graph
    return graph


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
    graph = graph_for(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    state = await graph.aget_state(config)
    if not state.next or state.values.get("resolved"):
        return {"paused": False}
    messages = state.values.get("messages", [])
    ai_texts = [m.content for m in messages if getattr(m, "type", "") == "ai"]
    return {
        "status": "pending",
        "paused": True,
        **await card_fields(user_id, state.values, ai_texts[-1] if ai_texts else ""),
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
    graph = graph_for(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    state = await graph.aget_state(config)
    if not state.next or state.values.get("resolved"):
        return
    await graph.aupdate_state(config, {"resolved": True}, as_node="present")


async def handle_meal_logging(
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
    # The graph is LangGraph, not Pydantic AI, so the agent span is written
    # here with the OTel GenAI attributes Logfire's Agents view reads.
    thread_id = config["configurable"]["thread_id"]
    with logfire.span(
        "invoke_agent meal_logging",
        **{
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": "meal_logging",
            "gen_ai.conversation.id": thread_id,
            "gen_ai.request.model": FLASH_LITE_MODEL,
            "gen_ai.input.messages": _genai_messages("user", user_input),
        },
    ) as span:
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
        response: dict[str, Any] = {
            "status": "success",
            "message": last_ai.content if last_ai else "",
            "paused": still_paused,
            "items": [],
        }
        if still_paused:
            response.update(await card_fields(user_id, result, response["message"]))
        else:
            response["meal_id"] = result.get("meal_id")
        span.set_attribute(
            "gen_ai.output.messages",
            _genai_messages("assistant", response["message"]),
        )
        return response


def _genai_messages(role: str, text: str) -> str:
    """One message in the OTel GenAI message format, as a JSON string."""
    return json.dumps([{"role": role, "parts": [{"type": "text", "content": text}]}])
