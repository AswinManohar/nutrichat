from __future__ import annotations

import os

import httpx
from fastapi import HTTPException, Request
from jose import JWTError, jwt

_JWT_SECRET_ENV = "SUPABASE_JWT_SECRET"
_SUPABASE_URL_ENV = "SUPABASE_URL"
_JWKS_PATH = "/auth/v1/.well-known/jwks.json"
_AUDIENCE = "authenticated"
_ASYMMETRIC_ALGORITHMS = ("ES256", "RS256")

# Module-level JWKS cache, keyed by "kid". Refetched once on cache miss
# since Supabase rotates signing keys.
_jwks_cache: dict[str, dict] = {}


class AuthError(HTTPException):
    """Raised when a request's bearer token is missing or invalid."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=401, detail=detail)


async def _fetch_jwks() -> dict[str, dict]:
    """Fetch the Supabase project's JWKS and index it by key ID.

    Returns:
        Mapping of `kid` to JWK dict, as returned by the project's
        public `.well-known/jwks.json` endpoint.

    Raises:
        AuthError: If the JWKS endpoint is unreachable or misconfigured.
    """
    supabase_url = os.environ.get(_SUPABASE_URL_ENV)
    if not supabase_url:
        raise AuthError("Server is not configured for authentication")

    url = f"{supabase_url}{_JWKS_PATH}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise AuthError("Unable to verify token: JWKS unavailable") from exc

    return {key["kid"]: key for key in data.get("keys", []) if "kid" in key}


async def _get_jwk_for_kid(kid: str) -> dict:
    """Return the JWK matching `kid`, refetching the JWKS once on a miss.

    Args:
        kid: The `kid` claim from the token's header.

    Returns:
        The JWK dict for the matching key.

    Raises:
        AuthError: If no key with `kid` is found even after refetching.
    """
    if kid not in _jwks_cache:
        _jwks_cache.update(await _fetch_jwks())

    jwk_for_kid = _jwks_cache.get(kid)
    if jwk_for_kid is None:
        raise AuthError("Invalid or expired token")

    return jwk_for_kid


def _normalize_audience(payload: dict) -> bool:
    """Check whether a decoded payload's `aud` claim is "authenticated".

    Args:
        payload: Decoded JWT payload.

    Returns:
        True if `aud` is `"authenticated"` or a list containing it.
    """
    aud = payload.get("aud")
    if isinstance(aud, list):
        return _AUDIENCE in aud
    return aud == _AUDIENCE


async def get_current_user_id(request: Request) -> str:
    """Resolve the Supabase Auth user ID for the current request.

    Validates the `Authorization: Bearer <token>` header and returns the
    `sub` claim. HS256 tokens are verified against the legacy
    `SUPABASE_JWT_SECRET`. ES256/RS256 tokens (the current Supabase
    default) are verified against the project's JWKS.

    Args:
        request: Incoming FastAPI request.

    Returns:
        The Supabase Auth UUID for the authenticated user.

    Raises:
        AuthError: If the header is missing/malformed or the token is
            invalid, expired, or has the wrong audience.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise AuthError("Missing or malformed Authorization header")

    token = auth_header.removeprefix("Bearer ").strip()

    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise AuthError("Invalid or expired token") from exc

    algorithm = header.get("alg")

    try:
        if algorithm == "HS256":
            secret = os.environ.get(_JWT_SECRET_ENV)
            if not secret:
                raise AuthError("Server is not configured for authentication")
            payload = jwt.decode(
                token, secret, algorithms=["HS256"], audience=_AUDIENCE
            )
        elif algorithm in _ASYMMETRIC_ALGORITHMS:
            kid = header.get("kid")
            if not kid:
                raise AuthError("Invalid or expired token")
            key = await _get_jwk_for_kid(kid)
            payload = jwt.decode(token, key, algorithms=[algorithm], audience=_AUDIENCE)
        else:
            raise AuthError("Invalid or expired token")
    except JWTError as exc:
        raise AuthError("Invalid or expired token") from exc

    if not _normalize_audience(payload):
        raise AuthError("Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("Token missing 'sub' claim")

    return user_id
