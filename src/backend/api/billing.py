from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from backend.auth.supabase import get_current_user_id
from backend.db.session import get_session
from backend.quota import PAID_QUOTA

router = APIRouter(prefix="/billing", tags=["billing"])


class UpgradeResponse(BaseModel):
    upgraded: bool
    new_quota: int

    model_config = ConfigDict(extra="forbid")


_TRUTHY = {"1", "true", "yes"}


def _dev_upgrade_enabled() -> bool:
    """Return True when BILLING_DEV_UPGRADE_ENABLED is truthy (read per request)."""
    return os.environ.get("BILLING_DEV_UPGRADE_ENABLED", "").strip().lower() in _TRUTHY


_UPGRADE_SQL = text("""
    UPDATE user_goal
       SET llm_quota = :paid_quota
     WHERE user_id = :user_id
    RETURNING llm_quota
""")


@router.post("/upgrade", response_model=UpgradeResponse)
async def upgrade_quota(
    user_id: str = Depends(get_current_user_id),
) -> UpgradeResponse:
    """Set the user's LLM quota to the paid tier without resetting usage.

    Requires an existing user_goal row (user must have completed onboarding).

    Args:
        user_id: Supabase Auth UUID resolved from the bearer token.

    Returns:
        UpgradeResponse confirming the new quota.

    Raises:
        HTTPException 404: If the dev upgrade flag is off, or if no user_goal
            row exists for this user.
    """
    if not _dev_upgrade_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(_UPGRADE_SQL, {"user_id": user_id, "paid_quota": PAID_QUOTA})
        await session.commit()
        row = result.fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="User profile not found. Complete onboarding first.",
        )

    return UpgradeResponse(upgraded=True, new_quota=row[0])
