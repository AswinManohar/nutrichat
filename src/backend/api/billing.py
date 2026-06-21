from __future__ import annotations

from fastapi import APIRouter, Depends
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


_UPGRADE_SQL = text("""
    INSERT INTO user_goal (user_id, llm_quota)
    VALUES (:user_id, :paid_quota)
    ON CONFLICT (user_id) DO UPDATE
      SET llm_quota = :paid_quota
    RETURNING llm_quota
""")


@router.post("/upgrade", response_model=UpgradeResponse)
async def upgrade_quota(
    user_id: str = Depends(get_current_user_id),
) -> UpgradeResponse:
    """Set the user's LLM quota to the paid tier without resetting usage.

    Args:
        user_id: Supabase Auth UUID resolved from the bearer token.

    Returns:
        UpgradeResponse confirming the new quota.
    """
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(_UPGRADE_SQL, {"user_id": user_id, "paid_quota": PAID_QUOTA})
        await session.commit()
        row = result.fetchone()

    return UpgradeResponse(upgraded=True, new_quota=row[0])
