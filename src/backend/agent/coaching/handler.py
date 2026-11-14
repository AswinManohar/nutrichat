"""Coaching turn handling: quota, the coaching agent, persisting the reply."""

from __future__ import annotations

from typing import Any

from opentelemetry import trace

from backend import tracing
from backend.agent.coaching.agent import CoachingAgent, RestrictionsUnavailableError
from backend.agent.coaching.store import link_recommendation, save_coaching_response
from backend.agent.llm import COACHING_MODEL
from backend.agent.turn import turn_response
from backend.config import get_tunables
from backend.quota import UPGRADE_MSG, consume_llm_credit

_TUNABLES = get_tunables()

_coaching_agent = CoachingAgent()


async def handle_coaching(
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
            ``glide.log_offer_text``. Never added to the upgrade message.
        routing: GLiDE's routing record for this turn, stored beside Gemini's
            parse as ``parsed_query["routing"]``; None when GLiDE gave no answer.

    Returns:
        Dict with status, message, paused=False, items=[] — same shape as
        meal logging so web and Telegram channels stay uniform — plus
        response_id when the reply was persisted, and recipe (the checked
        Recipe as a dict) with recommendation_id and constraint_note when the
        reply is a recipe.
        When the hard profile cannot be loaded the message is
        ``safety.profile_unavailable_text`` and nothing is persisted.
    """
    granted = await consume_llm_credit(user_id)
    if not granted:
        return turn_response(UPGRADE_MSG)
    with tracing.stage_span(tracing.COACHING_TURN) as span:
        try:
            result = await _coaching_agent.handle(user_id, user_input, conversation_id)
        except RestrictionsUnavailableError:
            # Never answer without the patient's binding profile (FR-007).
            span.set_attribute("profile_unavailable", True)
            return turn_response(_TUNABLES.safety.profile_unavailable_text)
        if offer_to_log and result.readback is None:
            # Appended after citations were extracted, so [n] parsing is
            # untouched; saved and remembered with the offer included.
            result = result.model_copy(
                update={
                    "message": (f"{result.message}\n\n{_TUNABLES.glide.log_offer_text}")
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
        if response_id is not None and result.recommendation_id is not None:
            await link_recommendation(result.recommendation_id, response_id)
        span.set_attribute("needs_guidance", result.parsed.needs_guidance)
        span.set_attribute("retrieved_count", len(result.retrieved))
        span.set_attribute("citation_count", len(result.citations))
        span.set_attribute("response_id", response_id or "")

    response = turn_response(result.message)
    if response_id is not None:
        response["response_id"] = response_id
    if result.recipe is not None:
        response["recipe"] = result.recipe.model_dump(mode="json")
        response["recommendation_id"] = result.recommendation_id
        response["constraint_note"] = result.constraint_note
    if result.readback is not None:
        response["readback"] = result.readback.model_dump()
    if result.facts_extracted:
        response["facts_extracted"] = True
    return response
