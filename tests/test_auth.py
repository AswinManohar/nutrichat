from __future__ import annotations

import base64
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

import backend.auth.supabase as supabase_auth
from backend.auth.supabase import AuthError, get_current_user_id

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


def _b64url_uint(value: int, length: int = 32) -> str:
    """Base64url-encode an unsigned integer as a fixed-length byte string."""
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


def _make_es256_token_and_jwk(
    *, kid: str = "test-kid", sub: str = "user-456", audience: str = "authenticated"
) -> tuple[str, dict]:
    """Generate an ES256-signed JWT and the matching public JWK."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = jwt.encode(
        {"sub": sub, "aud": audience, "exp": int(time.time()) + 3600},
        pem.decode(),
        algorithm="ES256",
        headers={"kid": kid},
    )
    numbers = private_key.public_key().public_numbers()
    public_jwk = {
        "kty": "EC",
        "crv": "P-256",
        "alg": "ES256",
        "kid": kid,
        "x": _b64url_uint(numbers.x),
        "y": _b64url_uint(numbers.y),
    }
    return token, public_jwk


@pytest.fixture(autouse=True)
def _clear_jwks_cache() -> None:
    """Ensure each test starts with an empty module-level JWKS cache."""
    supabase_auth._jwks_cache.clear()


def test_es256_token_verified_via_jwks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("DEV_BYPASS_AUTH", raising=False)
    token, public_jwk = _make_es256_token_and_jwk()
    supabase_auth._jwks_cache[public_jwk["kid"]] = public_jwk

    client = TestClient(_make_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "user-456"}


def test_es256_unknown_kid_triggers_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("DEV_BYPASS_AUTH", raising=False)
    token, public_jwk = _make_es256_token_and_jwk(kid="rotated-kid")
    # Cache is empty -> must refetch to find "rotated-kid".

    async def fake_fetch_jwks() -> dict[str, dict]:
        return {public_jwk["kid"]: public_jwk}

    monkeypatch.setattr(supabase_auth, "_fetch_jwks", fake_fetch_jwks)

    client = TestClient(_make_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "user-456"}
    assert "rotated-kid" in supabase_auth._jwks_cache


def test_es256_kid_still_missing_after_refetch_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("DEV_BYPASS_AUTH", raising=False)
    token, _ = _make_es256_token_and_jwk(kid="missing-kid")

    async def fake_fetch_jwks() -> dict[str, dict]:
        return {}

    monkeypatch.setattr(supabase_auth, "_fetch_jwks", fake_fetch_jwks)

    client = TestClient(_make_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_malformed_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _TEST_SECRET)
    monkeypatch.delenv("DEV_BYPASS_AUTH", raising=False)
    client = TestClient(_make_app())

    resp = client.get("/whoami", headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert resp.status_code == 401


def test_auth_error_is_401() -> None:
    err = AuthError("boom")
    assert err.status_code == 401
    assert err.detail == "boom"
