from __future__ import annotations

import logging
import os

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select, text

from backend.auth.supabase import get_current_user_id
from backend.db.models import (
    DailySummary,
    DeviceToken,
    IntegrationToken,
    MealLog,
    NutrientCheckup,
    PushSubscription,
    TelegramLink,
    UserGoal,
    UserMeal,
    UserMemory,
    WeeklySummary,
)
from backend.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["account"])

_SUPABASE_URL_ENV = "SUPABASE_URL"
_SERVICE_ROLE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"


async def _delete_auth_user(user_id: str) -> None:
    """Delete a user from Supabase Auth via the Admin API.

    Args:
        user_id: Supabase Auth UUID of the account to remove.

    Raises:
        RuntimeError: If the server is not configured for admin access, the
            Admin API returns a non-2xx status, or the request fails
            (timeout, connection error, etc.).
    """
    supabase_url = os.environ.get(_SUPABASE_URL_ENV)
    service_role_key = os.environ.get(_SERVICE_ROLE_KEY_ENV)
    if not supabase_url or not service_role_key:
        raise RuntimeError("Server is not configured for account deletion")

    url = f"{supabase_url}/auth/v1/admin/users/{user_id}"
    headers = {"Authorization": f"Bearer {service_role_key}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                if response.status // 100 != 2:
                    body = await response.text()
                    raise RuntimeError(
                        f"Supabase Admin API returned {response.status}: {body}"
                    )
    except aiohttp.ClientError as exc:
        raise RuntimeError(f"Supabase Admin API request failed: {exc}") from exc


@router.delete("/account", status_code=204)
async def delete_account(user_id: str = Depends(get_current_user_id)) -> Response:
    """Permanently delete the caller's account and all associated data.

    Ordering: the Supabase Auth user is deleted FIRST, then all database
    rows in a single transaction. This order is deliberate — if the DB pass
    fails after the auth user is already gone, the account is unusable but
    ops can retry the data cleanup later (the row is inert, not user-facing).
    The reverse order is worse: if DB deletion succeeded but auth deletion
    then failed, the user could still log in to a resurrected, empty
    account mid-failure. Auth-first fails closed: if the Admin API call
    fails, no database row is touched.

    Args:
        user_id: Supabase Auth UUID resolved from the bearer token.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 502 if the Supabase Admin API call fails. No data is
            deleted in that case.
    """
    try:
        await _delete_auth_user(user_id)
    except Exception as exc:
        logger.error("Failed to delete Supabase Auth user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=502, detail="Failed to delete account: auth service error"
        ) from exc

    session_factory = get_session()
    async with session_factory() as session:
        # Resolve Telegram chat ids before deleting telegram_link rows, so
        # we can also purge that chat's LangGraph checkpoint history below.
        chat_ids_result = await session.execute(
            select(TelegramLink.chat_id).where(TelegramLink.user_id == user_id)
        )
        chat_ids = chat_ids_result.scalars().all()

        # Tables with no FK cascade from user_goal need an explicit delete.
        await session.execute(
            delete(PushSubscription).where(PushSubscription.user_id == user_id)
        )

        # Tables below all cascade from user_goal (ondelete="CASCADE" on
        # their user_id FK): telegram_link, integration_token, device_token,
        # meal_log, user_meal, user_memory, daily_summary, weekly_summary,
        # nutrient_checkup. Deleted explicitly anyway for clarity and to
        # keep this endpoint correct even if a future migration drops a
        # cascade.
        await session.execute(
            delete(TelegramLink).where(TelegramLink.user_id == user_id)
        )
        await session.execute(
            delete(IntegrationToken).where(IntegrationToken.user_id == user_id)
        )
        await session.execute(delete(DeviceToken).where(DeviceToken.user_id == user_id))
        await session.execute(delete(MealLog).where(MealLog.user_id == user_id))
        await session.execute(delete(UserMeal).where(UserMeal.user_id == user_id))
        await session.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
        await session.execute(
            delete(DailySummary).where(DailySummary.user_id == user_id)
        )
        await session.execute(
            delete(WeeklySummary).where(WeeklySummary.user_id == user_id)
        )
        await session.execute(
            delete(NutrientCheckup).where(NutrientCheckup.user_id == user_id)
        )
        await session.execute(delete(UserGoal).where(UserGoal.user_id == user_id))

        # LangGraph checkpoint rows are not SQLAlchemy models (they're
        # created ad hoc by AsyncPostgresSaver.setup()); delete by raw SQL.
        # Web thread ids are namespaced "{user_id}:{conversation_id}" (see
        # api/meals.py); older/legacy rows may exist as the bare user_id.
        # We can't attribute client-generated UUID thread ids to a user, so
        # those are left behind (they carry no personal data on their own).
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            await session.execute(
                _delete_checkpoint_rows_sql(table),
                {"uid": user_id, "prefix": f"{user_id}:%"},
            )
            for chat_id in chat_ids:
                await session.execute(
                    _delete_checkpoint_rows_sql(table, telegram=True),
                    {"prefix": f"tg:{chat_id}:%"},
                )

        await session.commit()

    return Response(status_code=204)


def _delete_checkpoint_rows_sql(table: str, telegram: bool = False):
    """Build the raw DELETE statement for one LangGraph checkpoint table.

    Args:
        table: One of "checkpoints", "checkpoint_writes", "checkpoint_blobs".
        telegram: If True, match a Telegram chat's thread-id prefix
            (`tg:{chat_id}:%`); otherwise match the web user's own thread
            ids (`{user_id}` or `{user_id}:%`).

    Returns:
        A SQLAlchemy `text()` clause with bound parameter placeholders.
    """
    if telegram:
        return text(f"DELETE FROM {table} WHERE thread_id LIKE :prefix")
    return text(f"DELETE FROM {table} WHERE thread_id = :uid OR thread_id LIKE :prefix")
