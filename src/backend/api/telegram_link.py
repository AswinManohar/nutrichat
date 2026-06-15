"""Telegram account linking — short-lived codes + link status.

The web app generates a 6-digit code (stored in Redis with a 10-minute TTL)
that the user sends to the bot via `/link <code>`. The bot process (which
shares Redis and Postgres with the API) validates the code and writes the
`telegram_link` row directly — this module has no bind endpoint.
"""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select

from backend.auth.supabase import get_current_user_id
from backend.db.models import TelegramLink
from backend.db.redis_client import get_redis
from backend.db.session import get_session
from backend.telegram.auth import _USER_CACHE_PREFIX

router = APIRouter(prefix="/telegram", tags=["telegram"])

_LINK_CODE_TTL_S = 600
_LINK_CODE_PREFIX = "tglink:code:"


class LinkCodeResponse(BaseModel):
    code: str
    expires_in: int
    bot_username: str

    model_config = ConfigDict(extra="forbid")


class LinkStatusResponse(BaseModel):
    linked: bool

    model_config = ConfigDict(extra="forbid")


@router.post("/link-code")
async def create_link_code(
    user_id: str = Depends(get_current_user_id),
) -> LinkCodeResponse:
    """Generate a 6-digit Telegram link code, valid for 10 minutes.

    Args:
        user_id: Supabase Auth UUID of the requesting user.

    Returns:
        The code, its TTL in seconds, and the bot's username for the
        Settings page instructions.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    client = get_redis()
    await client.set(f"{_LINK_CODE_PREFIX}{code}", user_id, ex=_LINK_CODE_TTL_S)

    bot_username = os.environ.get("TELEGRAM_BOT_USERNAME", "")
    return LinkCodeResponse(
        code=code, expires_in=_LINK_CODE_TTL_S, bot_username=bot_username
    )


@router.get("/link")
async def get_link_status(
    user_id: str = Depends(get_current_user_id),
) -> LinkStatusResponse:
    """Return whether the current user has a linked Telegram chat."""
    session_factory = get_session()
    async with session_factory() as session:
        existing = await session.scalar(
            select(TelegramLink).where(TelegramLink.user_id == user_id)
        )
        return LinkStatusResponse(linked=existing is not None)


@router.delete("/link", status_code=204)
async def delete_link(user_id: str = Depends(get_current_user_id)) -> None:
    """Unlink the current user's Telegram chat, if any.

    Also clears the Redis `tguser:<chat_id>` cache so the bot stops
    granting access to the unlinked chat immediately, rather than waiting
    out the cache's 1-hour TTL.
    """
    session_factory = get_session()
    async with session_factory() as session:
        chat_id = await session.scalar(
            select(TelegramLink.chat_id).where(TelegramLink.user_id == user_id)
        )
        result = await session.execute(
            delete(TelegramLink).where(TelegramLink.user_id == user_id)
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="No linked Telegram chat")

    client = get_redis()
    await client.delete(f"{_USER_CACHE_PREFIX}{chat_id}")
