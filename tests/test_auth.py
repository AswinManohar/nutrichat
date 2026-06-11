from __future__ import annotations

import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from backend.auth.supabase import get_current_user_id

_TEST_SECRET = "test-jwt-secret"


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user_id: str = Depends(get_current_user_id)) -> dict:
        return {"user_id": user_id}

    return app


def _make_token(
    *,
    secret: str = _TEST_SECRET,
    sub: str | None = "user-123",
    audience: str = "authenticated",
    exp_offset: int = 3600,
    algorithm: str = "HS256",
) -> str:
    payload = {"aud": audience, "exp": int(time.time()) + exp_offset}
    if sub is not None:
        payload["sub"] = sub
    return jwt.encode(payload, secret, algorithm=algorithm)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _TEST_SECRET)
    monkeypatch.delenv("DEV_BYPASS_AUTH", raising=False)
    return TestClient(_make_app())


def test_valid_token_returns_user_id(client: TestClient) -> None:
    token = _make_token()
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "user-123"}


def test_missing_header_returns_401(client: TestClient) -> None:
    resp = client.get("/whoami")
    assert resp.status_code == 401


def test_malformed_header_returns_401(client: TestClient) -> None:
    resp = client.get("/whoami", headers={"Authorization": "NotBearer abc"})
    assert resp.status_code == 401


def test_expired_token_returns_401(client: TestClient) -> None:
    token = _make_token(exp_offset=-3600)
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_wrong_secret_returns_401(client: TestClient) -> None:
    token = _make_token(secret="wrong-secret")
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_wrong_audience_returns_401(client: TestClient) -> None:
    token = _make_token(audience="other-audience")
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_missing_sub_claim_returns_401(client: TestClient) -> None:
    token = _make_token(sub=None)
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_dev_bypass_uses_debug_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    client = TestClient(_make_app())

    resp = client.get("/whoami", headers={"X-Debug-User-Id": "debug-user"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "debug-user"}


def test_dev_bypass_without_header_falls_back_to_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    client = TestClient(_make_app())

    resp = client.get("/whoami")
    assert resp.status_code == 401
