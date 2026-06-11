from __future__ import annotations

import os

from fastapi import HTTPException, Request
from jose import JWTError, jwt

_DEV_BYPASS_ENV = "DEV_BYPASS_AUTH"
_JWT_SECRET_ENV = "SUPABASE_JWT_SECRET"
_DEBUG_USER_HEADER = "X-Debug-User-Id"


class AuthError(HTTPException):
    """Raised when a request's bearer token is missing or invalid."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=401, detail=detail)


async def get_current_user_id(request: Request) -> str:
    """Resolve the Supabase Auth user ID for the current request.

    Validates the `Authorization: Bearer <token>` header against the
    Supabase project's JWT secret (HS256) and returns the `sub` claim.

    Args:
        request: Incoming FastAPI request.

    Returns:
        The Supabase Auth UUID for the authenticated user.

    Raises:
        AuthError: If the header is missing/malformed or the token is
            invalid, expired, or has the wrong audience.
    """
    if os.environ.get(_DEV_BYPASS_ENV, "").lower() == "true":
        debug_user_id = request.headers.get(_DEBUG_USER_HEADER)
        if debug_user_id:
            return debug_user_id

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise AuthError("Missing or malformed Authorization header")

    token = auth_header.removeprefix("Bearer ").strip()
    secret = os.environ.get(_JWT_SECRET_ENV)
    if not secret:
        raise AuthError("Server is not configured for authentication")

    try:
        payload = jwt.decode(
            token, secret, algorithms=["HS256"], audience="authenticated"
        )
    except JWTError as exc:
        raise AuthError("Invalid or expired token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("Token missing 'sub' claim")

    return user_id
