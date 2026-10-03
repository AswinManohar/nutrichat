from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import integrations
from backend.auth.supabase import AuthError

_USER_A = "00000000-0000-0000-0000-00000000000a"
_USER_B = "00000000-0000-0000-0000-00000000000b"


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(integrations.router, user_id=None))


def _meal_row(
    meal_id: str,
    updated_at: datetime,
    *,
    user_id: str = _USER_A,
    deleted_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        meal_id=meal_id,
        user_id=user_id,
        logged_at=updated_at,
        meal_type="lunch",
        kcal=500.0,
        protein_g=40.0,
        carbs_g=30.0,
        fat_g=15.0,
        fiber_g=6.0,
        entities=[{"food_name": "egg", "micros": {"iron": [1.0, "u"]}}],
        flags={},
        updated_at=updated_at,
        deleted_at=deleted_at,
    )


def _auth(user_id: str = _USER_A):
    async def _fake_get_integration_user() -> str:
        return user_id

    return _fake_get_integration_user


_T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_T1 = datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------


def test_cursor_round_trip() -> None:
    cursor = integrations._encode_cursor(_T0, "abc-123")
    decoded_at, decoded_id = integrations._decode_cursor(cursor)
    assert decoded_at == _T0
    assert decoded_id == "abc-123"


def test_invalid_cursor_raises_400(client: TestClient) -> None:
    app = client.app
    app.dependency_overrides[integrations.get_integration_user] = _auth()

    resp = client.get("/v1/integrations/meals", params={"since": "not-base64!!"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /meals — pagination, tombstones, isolation
# ---------------------------------------------------------------------------


def test_meals_cursor_idempotency(
    client: TestClient,
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    """Re-polling with the same cursor returns the same next page."""
    app = client.app
    app.dependency_overrides[integrations.get_integration_user] = _auth()

    rows = [_meal_row("meal-1", _T0), _meal_row("meal-2", _T1)]
    session = MagicMock()
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    session.execute = AsyncMock(return_value=result)
    factory = mock_session_factory(session)

    with patch("backend.api.integrations.get_session", return_value=factory):
        resp1 = client.get("/v1/integrations/meals", params={"limit": 1})
        resp2 = client.get("/v1/integrations/meals", params={"limit": 1})

    assert resp1.status_code == resp2.status_code == 200
    assert resp1.json() == resp2.json()
    assert resp1.json()["has_more"] is True
    assert resp1.json()["next_cursor"] is not None


def test_meals_surfaces_tombstone_for_soft_deleted(
    client: TestClient,
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    app = client.app
    app.dependency_overrides[integrations.get_integration_user] = _auth()

    rows = [_meal_row("meal-1", _T1, deleted_at=_T1)]
    session = MagicMock()
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    session.execute = AsyncMock(return_value=result)
    factory = mock_session_factory(session)

    with patch("backend.api.integrations.get_session", return_value=factory):
        resp = client.get("/v1/integrations/meals")

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["deleted"] is True
    assert item["meal_id"] == "meal-1"
    assert item["kcal"] is None
    assert item["entities"] is None


def test_meals_edit_resurfaces_with_new_values(
    client: TestClient,
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    """An edited (updated_at-bumped) meal reappears with its new values."""
    app = client.app
    app.dependency_overrides[integrations.get_integration_user] = _auth()

    edited = _meal_row("meal-1", _T1)
    edited.kcal = 999.0
    session = MagicMock()
    result = MagicMock()
    result.all = MagicMock(return_value=[edited])
    session.execute = AsyncMock(return_value=result)
    factory = mock_session_factory(session)

    with patch("backend.api.integrations.get_session", return_value=factory):
        resp = client.get(
            "/v1/integrations/meals",
            params={"since": integrations._encode_cursor(_T0, "meal-0")},
        )

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["deleted"] is False
    assert item["kcal"] == 999.0


def test_meals_per_user_isolation(
    client: TestClient,
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    """The user_id from the token is what scopes the query — verify it's used."""
    app = client.app
    app.dependency_overrides[integrations.get_integration_user] = _auth(_USER_B)

    session = MagicMock()
    result = MagicMock()
    result.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=result)
    factory = mock_session_factory(session)

    with patch("backend.api.integrations.get_session", return_value=factory):
        resp = client.get("/v1/integrations/meals")

    assert resp.status_code == 200
    assert resp.json()["items"] == []
    params = session.execute.call_args[0][1]
    assert params["user_id"] == _USER_B


# ---------------------------------------------------------------------------
# Auth — read-only scope enforcement
# ---------------------------------------------------------------------------


def test_missing_token_returns_401(client: TestClient) -> None:
    resp = client.get("/v1/integrations/meals")
    assert resp.status_code == 401


def test_get_integration_user_rejects_missing_scope(
    mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    from backend.auth import integration as auth_integration

    async def _run() -> None:
        request = MagicMock()
        request.headers = {"Authorization": "Bearer nck_test"}

        row = SimpleNamespace(id="tok-1", user_id=_USER_A, scopes=["other:scope"])
        session = MagicMock()
        result = MagicMock()
        result.first = MagicMock(return_value=row)
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()
        factory = mock_session_factory(session)

        with patch("backend.auth.integration.get_session", return_value=factory):
            with pytest.raises(AuthError):
                await auth_integration.get_integration_user(request)

    import asyncio

    asyncio.run(_run())


def test_get_integration_user_rejects_revoked_token(
    mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    from backend.auth import integration as auth_integration

    async def _run() -> None:
        request = MagicMock()
        request.headers = {"Authorization": "Bearer nck_test"}

        session = MagicMock()
        result = MagicMock()
        result.first = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)
        factory = mock_session_factory(session)

        with patch("backend.auth.integration.get_session", return_value=factory):
            with pytest.raises(AuthError):
                await auth_integration.get_integration_user(request)

    import asyncio

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    app = client.app
    app.dependency_overrides[integrations.get_integration_user] = _auth()

    resp = client.get("/v1/integrations/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": integrations.API_VERSION}
