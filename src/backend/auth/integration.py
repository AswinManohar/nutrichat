from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import text as sa_text

from backend.auth.supabase import AuthError
from backend.db.session import get_session

_REQUIRED_SCOPE = "nutrition:read"


def _extract_token(request: Request) -> str:
    """Pull the bearer/API-key token out of the request headers.

    Args:
        request: Incoming FastAPI request.

    Returns:
        The raw token string (without the `Bearer ` prefix).

    Raises:
        AuthError: If neither header is present or malformed.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header:
        if not auth_header.startswith("Bearer "):
            raise AuthError("Malformed Authorization header")
        return auth_header.removeprefix("Bearer ").strip()

    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key.strip()

    raise AuthError("Missing Authorization or X-API-Key header")


async def get_integration_user(request: Request) -> str:
    """Resolve the user ID for a service-token-authenticated integration request.

    Validates the token against `integration_token.token_hash` (SHA-256),
    requires the token to be unrevoked and carry the `nutrition:read` scope,
    and best-effort updates `last_used_at`.

    Args:
        request: Incoming FastAPI request.

    Returns:
        The `user_id` (Supabase Auth UUID) the token belongs to.

    Raises:
        AuthError: If the token is missing, unknown, revoked, or lacks the
            required scope.
    """
    token = _extract_token(request)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT id, user_id, scopes FROM integration_token "
                "WHERE token_hash = :token_hash AND revoked_at IS NULL"
            ),
            {"token_hash": token_hash},
        )
        row = result.first()
        if row is None:
            raise AuthError("Invalid or revoked token")
        if _REQUIRED_SCOPE not in row.scopes:
            raise AuthError("Token missing required scope: nutrition:read")

        await session.execute(
            sa_text(
                "UPDATE integration_token SET last_used_at = :now WHERE id = :id"
            ),
            {"now": datetime.now(timezone.utc), "id": row.id},
        )
        await session.commit()

        return row.user_id
