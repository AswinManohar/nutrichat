from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import devices


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(devices.router, header_auth=True))


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Debug-User-Id": user_id}


def test_register_upserts_on_token(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    factory = mock_session_factory(session)

    body = {"token": "fcm-abc", "platform": "fcm"}
    with patch("backend.api.devices.get_session", return_value=factory):
        r1 = client.post("/devices/register", json=body, headers=_auth_headers("u1"))
        assert r1.status_code == 201

        r2 = client.post("/devices/register", json=body, headers=_auth_headers("u1"))
        assert r2.status_code == 201  # upsert, not conflict

    assert session.execute.await_count == 2


def test_delete_token(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    factory = mock_session_factory(session)

    with patch("backend.api.devices.get_session", return_value=factory):
        client.post(
            "/devices/register",
            json={"token": "fcm-x", "platform": "fcm"},
            headers=_auth_headers("u1"),
        )
        resp = client.delete("/devices/fcm-x", headers=_auth_headers("u1"))

    assert resp.status_code == 204


def test_register_rejects_unknown_platform(client: TestClient) -> None:
    resp = client.post(
        "/devices/register",
        json={"token": "t", "platform": "apns"},
        headers=_auth_headers("u1"),
    )
    assert resp.status_code == 422


def test_register_requires_auth(
    monkeypatch: pytest.MonkeyPatch, app_factory: Callable[..., FastAPI]
) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    client = TestClient(app_factory(devices.router, user_id=None))

    resp = client.post("/devices/register", json={"token": "t", "platform": "fcm"})
    assert resp.status_code == 401
