"""Thumbs up/down on a persisted coaching reply."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

import logfire
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.supabase import get_current_user_id
from backend.db.models import CoachingResponse
from backend.db.session import get_session
from backend.ratelimit import user_rate_limiter

router = APIRouter(prefix="/coaching", tags=["coaching"])

# Per user per minute. Ratings are cheap but each is a DB write.
FEEDBACK_RATE_LIMIT = 60


class FeedbackRequest(BaseModel):
    """Body for POST /coaching/{response_id}/feedback."""

    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")


class FeedbackResponse(BaseModel):
    """Response for POST /coaching/{response_id}/feedback."""

    response_id: str
    rating: str

    model_config = ConfigDict(extra="forbid")


@router.post(
    "/{response_id}/feedback",
    dependencies=[
        Depends(user_rate_limiter("feedback", limit=FEEDBACK_RATE_LIMIT, window_s=60))
    ],
)
async def rate_response(
    response_id: uuid.UUID,
    req: FeedbackRequest,
    user_id: str = Depends(get_current_user_id),
) -> FeedbackResponse:
    """Store or overwrite the caller's rating of one coaching reply.

    Returns 404 both for unknown ids and for replies that belong to
    another user, so ids cannot be probed.
    """
    session_factory = get_session()
    async with session_factory() as session:
        row = await session.get(CoachingResponse, str(response_id))
        if row is None or row.user_id != user_id:
            raise HTTPException(status_code=404, detail="Coaching response not found")
        row.rating = req.rating
        row.rating_comment = req.comment
        row.rated_at = datetime.now(UTC)
        await session.commit()
        logfire.info(
            "coaching_feedback",
            response_id=str(response_id),
            rating=req.rating,
            trace_id=row.trace_id,
        )
    return FeedbackResponse(response_id=str(response_id), rating=req.rating)
