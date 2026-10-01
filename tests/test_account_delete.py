from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import account

_UID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(account.router, header_auth=True))


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Debug-User-Id": user_id}


def _chat_id_row(chat_id: int) -> MagicMock:
    row = MagicMock()
    row.chat_id = chat_id
    return row


def test_delete_account_removes_all_rows(
    client: TestClient,
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    session = make_session()

    chat_rows = MagicMock()
    chat_rows.scalars.return_value.all.return_value = [12345]
    session.execute = AsyncMock(return_value=chat_rows)

    factory = mock_session_factory(session)

    with (
        patch("backend.api.account._delete_auth_user", new=AsyncMock()) as auth_del,
        patch("backend.api.account.get_session", return_value=factory),
    ):
        resp = client.delete("/account", headers=_auth_headers(_UID))

    assert resp.status_code == 204
    auth_del.assert_awaited_once_with(_UID)
    session.commit.assert_awaited_once()
    # 1 select (telegram chat_ids) + N deletes issued within the transaction
    assert session.execute.await_count >= 9

    # One of the deletes must target food_correction rows for this user
    # (spec 003, FR-012 / research R6): a corrected item's audit row must
    # not survive account deletion.
    deleted_tables = {
        call.args[0].table.name
        for call in session.execute.await_args_list
        if hasattr(call.args[0], "table")
    }
    assert "food_correction" in deleted_tables


def test_delete_account_fails_closed_when_auth_delete_fails(
    client: TestClient,
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    session = make_session()
    factory = mock_session_factory(session)

    with (
        patch(
            "backend.api.account._delete_auth_user",
            new=AsyncMock(side_effect=RuntimeError("supabase down")),
        ) as auth_del,
        patch("backend.api.account.get_session", return_value=factory),
    ):
        resp = client.delete("/account", headers=_auth_headers(_UID))

    assert resp.status_code == 502
    auth_del.assert_awaited_once_with(_UID)
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_delete_account_requires_auth(
    monkeypatch: pytest.MonkeyPatch, app_factory: Callable[..., FastAPI]
) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    client = TestClient(app_factory(account.router, user_id=None))

    resp = client.delete("/account")
    assert resp.status_code == 401


def test_delete_account_rejects_non_uuid_user_id(client: TestClient) -> None:
    with patch("backend.api.account._delete_auth_user", new=AsyncMock()) as auth_del:
        resp = client.delete(
            "/account", headers=_auth_headers("not-a-uuid; DROP TABLE")
        )

    assert resp.status_code == 400
    auth_del.assert_not_awaited()


def test_delete_auth_user_configures_a_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")

    captured: dict[str, object] = {}

    class _FakeResponse:
        status = 200

        async def text(self) -> str:
            return ""

        async def __aenter__(self) -> _FakeResponse:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

    class _FakeSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["timeout"] = kwargs.get("timeout")

        def delete(self, *args: object, **kwargs: object) -> _FakeResponse:
            return _FakeResponse()

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

    with patch("backend.api.account.aiohttp.ClientSession", _FakeSession):
        import asyncio

        asyncio.run(account._delete_auth_user(_UID))

    timeout = captured["timeout"]
    assert isinstance(timeout, aiohttp.ClientTimeout)
    assert timeout.total == account._ADMIN_API_TIMEOUT_S


def test_delete_account_502_and_zero_deletes_on_auth_timeout(
    client: TestClient,
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    session = make_session()
    factory = mock_session_factory(session)

    with (
        patch(
            "backend.api.account._delete_auth_user",
            new=AsyncMock(side_effect=TimeoutError("timed out")),
        ) as auth_del,
        patch("backend.api.account.get_session", return_value=factory),
    ):
        resp = client.delete("/account", headers=_auth_headers(_UID))

    assert resp.status_code == 502
    auth_del.assert_awaited_once_with(_UID)
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()
