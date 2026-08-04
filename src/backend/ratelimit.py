from __future__ import annotations

from collections.abc import Awaitable, Callable

import logfire
from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.db.redis_client import get_redis

# Paths that must never be throttled (probes, webhook handshakes).
EXEMPT_PATHS: frozenset[str] = frozenset({"/health"})


class RateLimitResult(BaseModel):
    """Outcome of a rate-limit check for one identity/scope pair."""

    allowed: bool
    remaining: int
    retry_after_s: int = 0

    model_config = ConfigDict(extra="forbid")


async def check_rate_limit(
    identity: str, scope: str, limit: int, window_s: int
) -> RateLimitResult:
    """Consume one request slot from a fixed-window Redis counter.

    Fails open: if Redis is unreachable the request is allowed and a
    warning is logged, so a cache outage degrades to "no throttling"
    rather than a full API outage.

    Args:
        identity: Per-client key, e.g. a user ID or client IP.
        scope: Logical bucket name, e.g. "chat" or "ip".
        limit: Maximum requests allowed per window.
        window_s: Window length in seconds.

    Returns:
        RateLimitResult with allowed, remaining, and retry_after_s set.
    """
    key = f"ratelimit:{scope}:{identity}"
    client = get_redis()
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_s)
        ttl = await client.ttl(key)
        if ttl < 0:
            # Key survived without a TTL (crash between INCR and EXPIRE);
            # re-arm it so the identity is never blocked forever.
            await client.expire(key, window_s)
            ttl = window_s
    except Exception as exc:  # noqa: BLE001 — any Redis failure fails open
        logfire.warning("ratelimit_redis_error", scope=scope, error=str(exc))
        return RateLimitResult(allowed=True, remaining=limit)

    if count > limit:
        return RateLimitResult(allowed=False, remaining=0, retry_after_s=max(ttl, 1))
    return RateLimitResult(allowed=True, remaining=limit - count)


def _too_many_requests(retry_after_s: int) -> HTTPException:
    """Build the canonical 429 response with a Retry-After header."""
    return HTTPException(
        status_code=429,
        detail="Rate limit exceeded. Try again shortly.",
        headers={"Retry-After": str(retry_after_s)},
    )


def user_rate_limiter(
    scope: str, limit: int, window_s: int
) -> Callable[..., Awaitable[None]]:
    """Build a FastAPI dependency that rate-limits per authenticated user.

    Args:
        scope: Logical bucket name, unique per endpoint group.
        limit: Maximum requests per user per window.
        window_s: Window length in seconds.

    Returns:
        An async dependency raising HTTP 429 when the user is over limit.
    """
    # Imported here to keep module import order free of auth's env checks.
    from backend.auth.supabase import get_current_user_id

    async def _dependency(
        user_id: str = Depends(get_current_user_id),
    ) -> None:
        result = await check_rate_limit(user_id, scope, limit, window_s)
        if not result.allowed:
            logfire.info("ratelimit_user_blocked", scope=scope, user_id=user_id)
            raise _too_many_requests(result.retry_after_s)

    return _dependency


def client_ip(request: Request) -> str:
    """Return the client IP, trusting only the proxy-appended XFF hop.

    Railway's edge proxy appends the real client IP as the last entry of
    X-Forwarded-For; any earlier entries are attacker-controllable, so
    only the last one is used. Falls back to the socket peer address.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        last_hop = forwarded.split(",")[-1].strip()
        if last_hop:
            return last_hop
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Coarse per-IP fixed-window limit applied to every non-exempt route."""

    def __init__(self, app, limit: int = 120, window_s: int = 60) -> None:
        super().__init__(app)
        self.limit = limit
        self.window_s = window_s

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        result = await check_rate_limit(
            client_ip(request), "ip", self.limit, self.window_s
        )
        if not result.allowed:
            logfire.info("ratelimit_ip_blocked", path=request.url.path)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again shortly."},
                headers={"Retry-After": str(result.retry_after_s)},
            )
        return await call_next(request)
