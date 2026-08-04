"""Tests for backend.ratelimit — Redis-backed API rate limiting."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.auth.supabase import get_current_user_id
from backend.ratelimit import (
    RateLimitMiddleware,
    check_rate_limit,
    user_rate_limiter,
)


class FakeRedis:
    """Minimal async Redis stand-in supporting incr/expire/ttl with fake time."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.now: int = 0

    def advance(self, seconds: int) -> None:
        self.now += seconds
        for key, expires_at in list(self.ttls.items()):
            if expires_at <= self.now:
                self.counts.pop(key, None)
                self.ttls.pop(key, None)

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        if key in self.counts:
            self.ttls[key] = self.now + seconds

    async def ttl(self, key: str) -> int:
        if key not in self.counts:
            return -2
        if key not in self.ttls:
            return -1
        return self.ttls[key] - self.now


class BrokenRedis:
    """Raises on every operation, simulating a Redis outage."""

    async def incr(self, key: str) -> int:
        raise ConnectionError("redis down")

    async def expire(self, key: str, seconds: int) -> None:
        raise ConnectionError("redis down")

    async def ttl(self, key: str) -> int:
        raise ConnectionError("redis down")


@pytest.fixture
def fake_redis():
    client = FakeRedis()
    with patch("backend.ratelimit.get_redis", return_value=client):
        yield client


# ---------------------------------------------------------------- core logic


async def test_first_request_allowed(fake_redis):
    result = await check_rate_limit("user-1", scope="chat", limit=5, window_s=60)
    assert result.allowed is True
    assert result.remaining == 4


async def test_requests_over_limit_blocked(fake_redis):
    for _ in range(5):
        result = await check_rate_limit("user-1", scope="chat", limit=5, window_s=60)
        assert result.allowed is True

    result = await check_rate_limit("user-1", scope="chat", limit=5, window_s=60)
    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after_s > 0


async def test_window_expiry_resets_count(fake_redis):
    for _ in range(6):
        await check_rate_limit("user-1", scope="chat", limit=5, window_s=60)

    fake_redis.advance(61)
    result = await check_rate_limit("user-1", scope="chat", limit=5, window_s=60)
    assert result.allowed is True


async def test_identities_and_scopes_isolated(fake_redis):
    for _ in range(6):
        await check_rate_limit("user-1", scope="chat", limit=5, window_s=60)

    other_user = await check_rate_limit("user-2", scope="chat", limit=5, window_s=60)
    other_scope = await check_rate_limit("user-1", scope="meals", limit=5, window_s=60)
    assert other_user.allowed is True
    assert other_scope.allowed is True


async def test_redis_outage_fails_open():
    with patch("backend.ratelimit.get_redis", return_value=BrokenRedis()):
        result = await check_rate_limit("user-1", scope="chat", limit=5, window_s=60)
    assert result.allowed is True


async def test_key_missing_ttl_gets_one_restored(fake_redis):
    """A counter key that lost its TTL must be re-expired, never immortal."""
    await check_rate_limit("user-1", scope="chat", limit=5, window_s=60)
    fake_redis.ttls.clear()  # simulate crash between INCR and EXPIRE

    await check_rate_limit("user-1", scope="chat", limit=5, window_s=60)
    key = next(iter(fake_redis.counts))
    assert await fake_redis.ttl(key) > 0


# ------------------------------------------------------- per-user dependency


def _user_limited_app() -> FastAPI:
    app = FastAPI()

    @app.post(
        "/chat",
        dependencies=[Depends(user_rate_limiter("chat", limit=3, window_s=60))],
    )
    async def chat() -> dict:
        return {"ok": True}

    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    return app


def test_user_endpoint_429_after_limit(fake_redis):
    client = TestClient(_user_limited_app())
    for _ in range(3):
        assert client.post("/chat").status_code == 200

    resp = client.post("/chat")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


def test_user_endpoint_other_user_unaffected(fake_redis):
    app = _user_limited_app()
    client = TestClient(app)
    for _ in range(4):
        client.post("/chat")

    app.dependency_overrides[get_current_user_id] = lambda: "user-2"
    assert client.post("/chat").status_code == 200


# ----------------------------------------------------------- IP middleware


def _ip_limited_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit=5, window_s=60)

    @app.get("/anything")
    async def anything() -> dict:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


def test_middleware_429_after_limit(fake_redis):
    client = TestClient(_ip_limited_app())
    for _ in range(5):
        assert client.get("/anything").status_code == 200

    resp = client.get("/anything")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


def test_middleware_health_exempt(fake_redis):
    client = TestClient(_ip_limited_app())
    for _ in range(20):
        assert client.get("/health").status_code == 200


def test_middleware_uses_last_xff_entry(fake_redis):
    """Only the proxy-appended (last) XFF hop is trusted, so a spoofed
    leading XFF value must not let a client rotate identities."""
    client = TestClient(_ip_limited_app())
    for i in range(6):
        resp = client.get(
            "/anything",
            headers={"X-Forwarded-For": f"1.2.3.{i}, 9.9.9.9"},
        )
    assert resp.status_code == 429


# ------------------------------------------------------------- app wiring


def test_main_app_has_ip_rate_limit_middleware():
    from backend.main import app as main_app

    middleware_classes = [m.cls for m in main_app.user_middleware]
    assert RateLimitMiddleware in middleware_classes


def test_meals_log_endpoint_is_user_rate_limited(fake_redis):
    from unittest.mock import AsyncMock, MagicMock

    from backend.api import meals as meals_module

    app = FastAPI()
    app.include_router(meals_module.router)
    app.state.checkpointer = MagicMock()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    with patch.object(
        meals_module, "handle_message", AsyncMock(return_value={"ok": True})
    ):
        client = TestClient(app)
        statuses = [
            client.post("/meals/log", json={"user_input": "2 eggs"}).status_code
            for _ in range(meals_module.CHAT_RATE_LIMIT + 1)
        ]

    assert statuses[0] == 200
    assert statuses[-1] == 429
