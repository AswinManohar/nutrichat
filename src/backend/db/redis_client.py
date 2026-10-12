from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from typing import Literal

import redis.asyncio as redis
from pydantic import BaseModel, ConfigDict, ValidationError
from redis.exceptions import RedisError
from sqlalchemy import func, select

from backend.config import get_tunables
from backend.core import nutrition_day as _nd

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()
_COACHING_HISTORY_TURNS = _TUNABLES.memory.coaching_history_turns
_COACHING_HISTORY_TTL_S = _TUNABLES.memory.coaching_history_ttl_s
_STAPLES_CACHE_TTL_S = _TUNABLES.memory.staples_cache_ttl_s

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
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0
    n_meals: int = 0

    model_config = ConfigDict(extra="forbid")


def current_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the [start, end) UTC bounds of the current nutrition day.

    Thin wrapper over ``backend.core.nutrition_day.current_day_bounds``.
    """
    return _nd.current_day_bounds(now)


def day_bounds_for_date(day: date) -> tuple[datetime, datetime]:
    """Return the nutrition-day [start, end) UTC window for a calendar date.

    Thin wrapper over ``backend.core.nutrition_day.day_bounds``.
    """
    return _nd.day_bounds(day)


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
                func.coalesce(func.sum(MealLog.carbs_g), 0.0),
                func.coalesce(func.sum(MealLog.fat_g), 0.0),
                func.coalesce(func.sum(MealLog.fiber_g), 0.0),
                func.count(MealLog.meal_id),
            ).where(
                MealLog.user_id == user_id,
                MealLog.logged_at >= start_utc,
                MealLog.logged_at < end_utc,
                MealLog.deleted_at.is_(None),
            )
        )
        kcal, protein_g, carbs_g, fat_g, fiber_g, n_meals = result.one()

    return TodayTotals(
        kcal=float(kcal),
        protein_g=float(protein_g),
        carbs_g=float(carbs_g),
        fat_g=float(fat_g),
        fiber_g=float(fiber_g),
        n_meals=int(n_meals),
    )


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


def _staples_key(user_id: str) -> str:
    return f"staples:{user_id}"


async def get_cached_staples(user_id: str) -> dict[str, list[str]] | None:
    """Return the cached staple foods for a user, or None on a miss.

    Best-effort: a Redis outage or a malformed entry is a miss, so the
    caller falls back to the database.

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        Meal type -> food names as cached by :func:`set_cached_staples`
        (possibly empty), or None when nothing usable is cached.
    """
    try:
        raw = await get_redis().get(_staples_key(user_id))
    except (RedisError, OSError) as exc:
        logger.warning("staples cache read failed for %s: %s", user_id, exc)
        return None
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    return {
        str(k): [str(f) for f in v] for k, v in value.items() if isinstance(v, list)
    }


async def set_cached_staples(user_id: str, staples: dict[str, list[str]]) -> None:
    """Cache a user's staple foods for ``memory.staples_cache_ttl_s``.

    Best-effort: a Redis outage is logged and swallowed. An empty result is
    cached too, so users with no staples do not hit the database each turn.

    Args:
        user_id: Supabase Auth UUID.
        staples: Output of ``agent.tools.history.get_staple_foods``.
    """
    try:
        await get_redis().set(
            _staples_key(user_id), json.dumps(staples), ex=_STAPLES_CACHE_TTL_S
        )
    except (RedisError, OSError) as exc:
        logger.warning("staples cache write failed for %s: %s", user_id, exc)
