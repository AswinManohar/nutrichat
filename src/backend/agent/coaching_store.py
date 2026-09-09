"""Persist one coaching turn to coaching_response. Never raises."""

from __future__ import annotations

import logging
import uuid

from backend.agent.coaching import CoachingResult
from backend.db.models import CoachingResponse
from backend.db.session import get_session

logger = logging.getLogger(__name__)


async def save_coaching_response(
    *,
    user_id: str,
    conversation_id: str | None,
    query: str,
    result: CoachingResult,
    model: str,
    trace_id: str | None,
) -> str | None:
    """Insert a coaching_response row and return its id.

    The reply has already been generated; persistence is bookkeeping for
    feedback and eval export, so a failure is logged and swallowed rather
    than surfaced to the user.

    Args:
        user_id: Supabase Auth UUID.
        conversation_id: Thread id from the request, if any.
        query: Raw user message.
        result: Output of CoachingAgent.handle().
        model: Model name used for the response (COACHING_MODEL).
        trace_id: OTel trace id as 32 hex chars, or None outside a trace.

    Returns:
        The new row's id as a string, or None if the write failed.
    """
    row_id = str(uuid.uuid4())
    try:
        session_factory = get_session()
        async with session_factory() as session:
            session.add(
                CoachingResponse(
                    id=row_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    query=query,
                    parsed_query=result.parsed.model_dump(mode="json"),
                    retrieved_chunk_ids=[c.id for c in result.retrieved],
                    citations=[c.model_dump() for c in result.citations],
                    response_text=result.message,
                    model=model,
                    trace_id=trace_id,
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.error("coaching_response write failed for %s: %s", user_id, exc)
        return None
    return row_id


__all__ = ["save_coaching_response"]
