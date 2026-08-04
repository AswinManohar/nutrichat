from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from backend.auth.supabase import get_current_user_id
from backend.db.models import UserGoal
from backend.db.session import get_session
from backend.quota import FREE_QUOTA, PAID_QUOTA

router = APIRouter(prefix="/quota", tags=["quota"])


class QuotaResponse(BaseModel):
    used: int
    limit: int
    remaining: int
    exhausted: bool
    tier: str

    model_config = ConfigDict(extra="forbid")


@router.get("", response_model=QuotaResponse)
async def get_quota(user_id: str = Depends(get_current_user_id)) -> QuotaResponse:
    """Return the authenticated user's LLM credit usage.

    Args:
        user_id: Supabase Auth UUID resolved from the bearer token.

    Returns:
        QuotaResponse with used, limit, remaining, exhausted, and tier.
    """
    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)

    if goal is None:
        return QuotaResponse(
            used=0,
            limit=FREE_QUOTA,
            remaining=FREE_QUOTA,
            exhausted=False,
            tier="free",
        )

    used = goal.llm_requests_used
    limit = goal.llm_quota
    remaining = max(0, limit - used)
    return QuotaResponse(
        used=used,
        limit=limit,
        remaining=remaining,
        exhausted=used >= limit,
        tier="paid" if limit >= PAID_QUOTA else "free",
    )
