from __future__ import annotations

import logfire
from sqlalchemy import text

from backend.db.session import get_session

FREE_QUOTA: int = 50
PAID_QUOTA: int = 150

_UPSERT_SQL = text("""
    INSERT INTO user_goal (user_id, llm_requests_used, llm_quota)
    VALUES (:user_id, 1, :free_quota)
    ON CONFLICT (user_id) DO UPDATE
      SET llm_requests_used = user_goal.llm_requests_used + 1
      WHERE user_goal.llm_requests_used < user_goal.llm_quota
    RETURNING llm_requests_used
""")


async def consume_llm_credit(user_id: str) -> bool:
    """Atomically increment the LLM request counter if under quota.

    Uses an upsert so new users without a user_goal row are initialised
    with FREE_QUOTA. Returns True if a credit was consumed (caller may
    proceed with the LLM call). Returns False if the user is at or over
    quota (caller must degrade gracefully).

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        True if a credit was consumed, False if the user is over quota.
    """
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            _UPSERT_SQL, {"user_id": user_id, "free_quota": FREE_QUOTA}
        )
        await session.commit()
        row = result.fetchone()

    granted = row is not None
    if granted:
        logfire.info("quota_credit_consumed", user_id=user_id, used=row[0])
    else:
        logfire.info("quota_exhausted", user_id=user_id)
    return granted
