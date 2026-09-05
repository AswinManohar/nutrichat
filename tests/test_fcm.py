"""FCM sender: sends per token, prunes dead tokens, no-ops unconfigured."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.push import fcm


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def _tokens_result(tokens: list[str]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = tokens
    return result


@pytest.fixture(autouse=True)
def _reset_app_cache() -> None:
    """Each test controls _get_app() via patching, not real firebase init."""
    fcm._app = None
    yield
    fcm._app = None


async def test_send_to_user_no_app_configured_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIREBASE_CREDENTIALS_JSON", raising=False)

    sent = await fcm.send_to_user("user-1", "hi", "body")

    assert sent == 0


async def test_send_to_user_no_tokens_returns_zero() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=_tokens_result([]))
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    with (
        patch.object(fcm, "_get_app", return_value=MagicMock()),
        patch("backend.push.fcm.get_session", return_value=factory),
    ):
        sent = await fcm.send_to_user("user-1", "hi", "body")

    assert sent == 0


async def test_send_to_user_sends_and_counts_successes() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=_tokens_result(["t1", "t2"]))
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    with (
        patch.object(fcm, "_get_app", return_value=MagicMock()),
        patch("backend.push.fcm.get_session", return_value=factory),
        patch.object(fcm, "_send_one", return_value=None) as send_one,
    ):
        sent = await fcm.send_to_user("user-1", "hi", "body")

    assert sent == 2
    assert send_one.call_count == 2


async def test_send_prunes_unregistered_token() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=_tokens_result(["dead-token"]))
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    err = fcm.messaging.UnregisteredError("gone")

    with (
        patch.object(fcm, "_get_app", return_value=MagicMock()),
        patch("backend.push.fcm.get_session", return_value=factory),
        patch.object(fcm, "_send_one", side_effect=err),
    ):
        sent = await fcm.send_to_user("user-1", "hi", "body")

    assert sent == 0
    # The delete for the dead token is the second execute() call (the
    # first fetched the token list).
    delete_call = session.execute.call_args_list[1]
    assert "device_token" in str(delete_call[0][0]).lower()
