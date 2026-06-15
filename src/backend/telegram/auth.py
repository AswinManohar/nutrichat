"""Resolve a Telegram chat_id to a NutriChat user_id, with Redis caching.

The `telegram_link` table is the source of truth; a Redis cache avoids a
Postgres round trip on every message. The cache is invalidated by `/link`
(overwrite) and unlink (no TTL-based staleness concern since `/start` on an
unlinked chat always re-checks Postgres on cache miss).
"""

from __future__ import annotations

from sqlalchemy import select

from backend.db.models import TelegramLink
from backend.db.redis_client import get_redis
from backend.db.session import get_session

_USER_CACHE_PREFIX = "tguser:"
_USER_CACHE_TTL_S = 3600


async def resolve_user_id(chat_id: int) -> str | None:
    """Return the NutriChat user_id linked to a Telegram chat, if any.

    Args:
        chat_id: Telegram chat ID.

    Returns:
        Supabase Auth UUID, or None if the chat is not linked.
    """
    client = get_redis()
    cache_key = f"{_USER_CACHE_PREFIX}{chat_id}"

    cached = await client.get(cache_key)
    if cached:
        return cached

    session_factory = get_session()
    async with session_factory() as session:
        user_id = await session.scalar(
            select(TelegramLink.user_id).where(TelegramLink.chat_id == chat_id)
        )

    if user_id:
        await client.set(cache_key, user_id, ex=_USER_CACHE_TTL_S)
    return user_id


async def cache_user_id(chat_id: int, user_id: str) -> None:
    """Cache a freshly-linked chat_id -> user_id mapping in Redis.

    Args:
        chat_id: Telegram chat ID.
        user_id: Supabase Auth UUID just bound to this chat.
    """
    client = get_redis()
    await client.set(f"{_USER_CACHE_PREFIX}{chat_id}", user_id, ex=_USER_CACHE_TTL_S)
