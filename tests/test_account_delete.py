from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import account


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(account.router)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app())


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Debug-User-Id": user_id}


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def _chat_id_row(chat_id: int) -> MagicMock:
    row = MagicMock()
    row.chat_id = chat_id
    return row


def test_delete_account_removes_all_rows(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    session = MagicMock()
    session.commit = AsyncMock()

    chat_rows = MagicMock()
    chat_rows.scalars.return_value.all.return_value = [12345]
    session.execute = AsyncMock(return_value=chat_rows)

    factory = _mock_session_factory(session)

    with (
        patch("backend.api.account._delete_auth_user", new=AsyncMock()) as auth_del,
        patch("backend.api.account.get_session", return_value=factory),
    ):
        resp = client.delete("/account", headers=_auth_headers("u1"))

    assert resp.status_code == 204
    auth_del.assert_awaited_once_with("u1")
    session.commit.assert_awaited_once()
    # 1 select (telegram chat_ids) + N deletes issued within the transaction
    assert session.execute.await_count >= 8


def test_delete_account_fails_closed_when_auth_delete_fails(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    with (
        patch(
            "backend.api.account._delete_auth_user",
            new=AsyncMock(side_effect=RuntimeError("supabase down")),
        ) as auth_del,
        patch("backend.api.account.get_session", return_value=factory),
    ):
        resp = client.delete("/account", headers=_auth_headers("u1"))

    assert resp.status_code == 502
    auth_del.assert_awaited_once_with("u1")
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_delete_account_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV_BYPASS_AUTH", raising=False)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    client = TestClient(_make_app())

    resp = client.delete("/account")
    assert resp.status_code == 401
