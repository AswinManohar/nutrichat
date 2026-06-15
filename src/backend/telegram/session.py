"""Per-chat active conversation thread, mirroring the web app's behavior.

The web app starts a fresh `conversationId` after each non-paused response
(`ChatPage.tsx:43-45`); the Telegram bot mirrors that here so LangGraph
thread history doesn't grow unbounded. The active thread_id for a chat is
kept in Redis while the meal-logging graph is paused (mid-confirmation) and
rotated to a new thread once a turn resolves.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from backend.db.redis_client import get_redis

_THREAD_KEY_PREFIX = "tgthread:"
_THREAD_KEY_TTL_S = 86400

_EDIT_KEY_PREFIX = "tgedit:"
_EDIT_KEY_TTL_S = 1800


def _new_thread_id(chat_id: int) -> str:
    """Return a fresh LangGraph thread_id for a Telegram chat."""
    return f"tg:{chat_id}:{uuid.uuid4()}"


async def get_thread_id(chat_id: int) -> str:
    """Return the active thread_id for a chat, creating one if absent.

    Args:
        chat_id: Telegram chat ID.

    Returns:
        The active LangGraph thread_id for this chat.
    """
    client = get_redis()
    key = f"{_THREAD_KEY_PREFIX}{chat_id}"

    thread_id = await client.get(key)
    if thread_id:
        return thread_id

    thread_id = _new_thread_id(chat_id)
    await client.set(key, thread_id, ex=_THREAD_KEY_TTL_S)
    return thread_id


async def rotate_thread(chat_id: int) -> None:
    """Start a fresh thread for a chat after a non-paused response.

    Args:
        chat_id: Telegram chat ID.
    """
    client = get_redis()
    key = f"{_THREAD_KEY_PREFIX}{chat_id}"
    await client.set(key, _new_thread_id(chat_id), ex=_THREAD_KEY_TTL_S)


async def set_edit_state(chat_id: int, state: dict[str, Any]) -> None:
    """Store the in-progress meal-edit state for a chat's paused card.

    Args:
        chat_id: Telegram chat ID.
        state: Dict with keys "items" (the paused `items` list), "qty"
            (str(index) -> overridden gram weight), and "swaps"
            (str(index) -> candidate food name).
    """
    client = get_redis()
    key = f"{_EDIT_KEY_PREFIX}{chat_id}"
    await client.set(key, json.dumps(state), ex=_EDIT_KEY_TTL_S)


async def get_edit_state(chat_id: int) -> Optional[dict[str, Any]]:
    """Return the stored meal-edit state for a chat, or None if absent.

    Args:
        chat_id: Telegram chat ID.

    Returns:
        The dict previously stored by `set_edit_state`, or None.
    """
    client = get_redis()
    key = f"{_EDIT_KEY_PREFIX}{chat_id}"
    raw = await client.get(key)
    if not raw:
        return None
    return json.loads(raw)


async def clear_edit_state(chat_id: int) -> None:
    """Remove the stored meal-edit state for a chat.

    Args:
        chat_id: Telegram chat ID.
    """
    client = get_redis()
    key = f"{_EDIT_KEY_PREFIX}{chat_id}"
    await client.delete(key)
