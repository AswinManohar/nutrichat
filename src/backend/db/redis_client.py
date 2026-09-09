from __future__ import annotations

import logging
import os
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import redis.asyncio as redis
from pydantic import BaseModel, ConfigDict, ValidationError
from redis.exceptions import RedisError
from sqlalchemy import func, select

from backend.config import get_tunables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()
_TODAY_KEY_TTL_S = _TUNABLES.redis.today_key_ttl_s
_COACHING_HISTORY_TURNS = _TUNABLES.memory.coaching_history_turns
_COACHING_HISTORY_TTL_S = _TUNABLES.memory.coaching_history_ttl_s
_DAY_TZ = ZoneInfo(_TUNABLES.day.timezone)
_DAY_RESET_HOUR = _TUNABLES.day.reset_hour

# Global connection pool
_redis_pool: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Returns the globally active Redis connection pool manager."""
    global _redis_pool
    if _redis_pool is None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _redis_pool = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    return _redis_pool


class TodayTotals(BaseModel):
    """Validated daily-tracker totals for the active user."""

    kcal: float = 0.0
    protein_g: float = 0.0
    fiber_g: float = 0.0
    n_meals: int = 0

    model_config = ConfigDict(extra="forbid")


def current_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the [start, end) UTC bounds of the current nutrition day.

    A nutrition day runs from ``reset_hour`` to ``reset_hour`` in the
    configured local timezone (see ``day.*`` in tunables.yaml). Anything
    logged before ``reset_hour`` belongs to the previous day, so today's
    totals appear to reset at exactly ``reset_hour`` local time.

    Args:
        now: Instant to evaluate. Defaults to the current time. A naive
            datetime is assumed to be UTC.

    Returns:
        ``(start_utc, end_utc)`` covering the active nutrition day.
    """
    if now is None:
        now = datetime.now(_DAY_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    now_local = now.astimezone(_DAY_TZ)

    # Shift back by reset_hour so the date() lands on the day that owns `now`.
    day_date = (now_local - timedelta(hours=_DAY_RESET_HOUR)).date()
    start_local = datetime.combine(day_date, time(hour=_DAY_RESET_HOUR), tzinfo=_DAY_TZ)
    end_local = start_local + timedelta(days=1)
    utc = ZoneInfo("UTC")
    return start_local.astimezone(utc), end_local.astimezone(utc)


async def get_today_totals(user_id: str) -> TodayTotals:
    """Return the user's consumed totals for the current nutrition day.

    Derived directly from ``meal_log`` rows within the active day window
    (``current_day_bounds``), so the rollover happens automatically at the
    configured reset hour — no background job has to fire for it. Deleted
    meals are excluded.
    """
    from backend.db.models import MealLog
    from backend.db.session import get_session

    start_utc, end_utc = current_day_bounds()
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            select(
                func.coalesce(func.sum(MealLog.kcal), 0.0),
                func.coalesce(func.sum(MealLog.protein_g), 0.0),
                func.coalesce(func.sum(MealLog.fiber_g), 0.0),
                func.count(MealLog.meal_id),
            ).where(
                MealLog.user_id == user_id,
                MealLog.logged_at >= start_utc,
                MealLog.logged_at < end_utc,
                MealLog.deleted_at.is_(None),
            )
        )
        kcal, protein_g, fiber_g, n_meals = result.one()

    return TodayTotals(
        kcal=float(kcal),
        protein_g=float(protein_g),
        fiber_g=float(fiber_g),
        n_meals=int(n_meals),
    )


async def increment_today(
    user_id: str, kcal: float, protein_g: float, fiber_g: float
) -> TodayTotals:
    """
    Pipelines increment transactions preventing double-submits.
    Automatically refreshes the 24h key TTL safely tracking macros.
    """
    client = get_redis()
    key = f"today:{user_id}"

    async with client.pipeline(transaction=True) as pipe:
        pipe.hincrbyfloat(key, "kcal", kcal)
        pipe.hincrbyfloat(key, "protein_g", protein_g)
        pipe.hincrbyfloat(key, "fiber_g", fiber_g)
        pipe.hincrby(key, "n_meals", 1)
        pipe.expire(key, _TODAY_KEY_TTL_S)  # Safety-net TTL; midnight cron also deletes
        results = await pipe.execute()

    # Map the returning mapped pipe responses securely:
    return TodayTotals(
        kcal=float(results[0]),
        protein_g=float(results[1]),
        fiber_g=float(results[2]),
        n_meals=int(results[3]),
    )


async def reset_day_key(user_id: str) -> None:
    """Unlink function utilized typically by Celery cron cleanup at midnight."""
    client = get_redis()
    key = f"today:{user_id}"
    await client.delete(key)


# ---------------------------------------------------------------------------
# Coaching conversation history (short-term, per user)
# ---------------------------------------------------------------------------


class CoachingTurn(BaseModel):
    """One message in the coaching agent's short-term conversation memory."""

    role: Literal["user", "assistant"]
    content: str

    model_config = ConfigDict(extra="forbid")


def _coaching_history_key(user_id: str) -> str:
    return f"coach_history:{user_id}"


async def append_coaching_turns(user_id: str, turns: list[CoachingTurn]) -> None:
    """Append turns to the user's coaching history, keeping only the newest.

    Best-effort: a Redis outage is logged and swallowed so a failed history
    write never fails the user's request. The list is trimmed to the last
    ``memory.coaching_history_turns`` exchanges (two messages each) and its
    TTL refreshed on every write.

    Args:
        user_id: Supabase Auth UUID.
        turns: Messages to append, in conversation order.
    """
    if not turns:
        return
    key = _coaching_history_key(user_id)
    keep = _COACHING_HISTORY_TURNS * 2
    try:
        client = get_redis()
        async with client.pipeline(transaction=True) as pipe:
            pipe.rpush(key, *(t.model_dump_json() for t in turns))
            pipe.ltrim(key, -keep, -1)
            pipe.expire(key, _COACHING_HISTORY_TTL_S)
            await pipe.execute()
    except (RedisError, OSError) as exc:
        logger.warning("coaching history write failed for %s: %s", user_id, exc)


async def get_coaching_history(user_id: str) -> list[CoachingTurn]:
    """Return the user's recent coaching history, oldest first.

    Best-effort: returns an empty list when Redis is unavailable. Entries
    that fail to parse are skipped rather than failing the whole read.

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        Up to ``2 * memory.coaching_history_turns`` messages.
    """
    key = _coaching_history_key(user_id)
    try:
        raw_items = await get_redis().lrange(key, 0, -1)
    except (RedisError, OSError) as exc:
        logger.warning("coaching history read failed for %s: %s", user_id, exc)
        return []

    turns: list[CoachingTurn] = []
    for raw in raw_items:
        try:
            turns.append(CoachingTurn.model_validate_json(raw))
        except ValidationError:
            logger.warning("skipping malformed coaching history entry for %s", user_id)
    return turns
