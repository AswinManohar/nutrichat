from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import coaching_feedback
from backend.db.models import CoachingResponse
from backend.ratelimit import RateLimitResult

RESPONSE_ID = "3f7c1a2e-9b4d-4c8e-8f1a-2b3c4d5e6f70"


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(coaching_feedback.router, header_auth=True))


@pytest.fixture
def anon_client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(coaching_feedback.router, user_id=None))


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch(
        "backend.ratelimit.check_rate_limit",
        new_callable=AsyncMock,
        return_value=RateLimitResult(allowed=True, remaining=59),
    ):
        yield


def _auth(user_id: str) -> dict[str, str]:
    return {"X-Debug-User-Id": user_id}


def _row(user_id: str) -> CoachingResponse:
    return CoachingResponse(
        id=RESPONSE_ID,
        user_id=user_id,
        query="q",
        parsed_query={},
        retrieved_chunk_ids=[],
        citations=[],
        response_text="r",
        model="m",
        trace_id="ab" * 16,
    )


@pytest.fixture
def session_with(
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> Callable[[CoachingResponse | None], MagicMock]:
    def build(row: CoachingResponse | None) -> MagicMock:
        return mock_session_factory(make_session(get_result=row))

    return build


def test_unauthenticated_returns_401(anon_client: TestClient) -> None:
    resp = anon_client.post(f"/coaching/{RESPONSE_ID}/feedback", json={"rating": "up"})
    assert resp.status_code == 401


def test_unknown_id_returns_404(
    client: TestClient, session_with: Callable[..., MagicMock]
) -> None:
    with patch(
        "backend.api.coaching_feedback.get_session", return_value=session_with(None)
    ):
        resp = client.post(
            f"/coaching/{RESPONSE_ID}/feedback",
            json={"rating": "up"},
            headers=_auth("user-1"),
        )
    assert resp.status_code == 404


def test_foreign_id_returns_404(
    client: TestClient, session_with: Callable[..., MagicMock]
) -> None:
    with patch(
        "backend.api.coaching_feedback.get_session",
        return_value=session_with(_row("someone-else")),
    ):
        resp = client.post(
            f"/coaching/{RESPONSE_ID}/feedback",
            json={"rating": "down"},
            headers=_auth("user-1"),
        )
    assert resp.status_code == 404


def test_rating_overwrites_prior_rating_and_sets_rated_at(
    client: TestClient, session_with: Callable[..., MagicMock]
) -> None:
    row = _row("user-1")
    row.rating = "up"
    factory = session_with(row)

    with patch("backend.api.coaching_feedback.get_session", return_value=factory):
        resp = client.post(
            f"/coaching/{RESPONSE_ID}/feedback",
            json={"rating": "down", "comment": "wrong number"},
            headers=_auth("user-1"),
        )

    assert resp.status_code == 200
    assert resp.json() == {"response_id": RESPONSE_ID, "rating": "down"}
    assert row.rating == "down"
    assert row.rating_comment == "wrong number"
    assert isinstance(row.rated_at, datetime)
    factory.return_value.commit.assert_awaited_once()


def test_comment_of_500_chars_is_accepted(
    client: TestClient, session_with: Callable[..., MagicMock]
) -> None:
    row = _row("user-1")
    factory = session_with(row)

    with patch("backend.api.coaching_feedback.get_session", return_value=factory):
        resp = client.post(
            f"/coaching/{RESPONSE_ID}/feedback",
            json={"rating": "up", "comment": "x" * 500},
            headers=_auth("user-1"),
        )

    assert resp.status_code == 200
    assert row.rating_comment == "x" * 500


def test_comment_over_500_chars_is_rejected(client: TestClient) -> None:
    resp = client.post(
        f"/coaching/{RESPONSE_ID}/feedback",
        json={"rating": "down", "comment": "x" * 501},
        headers=_auth("user-1"),
    )
    assert resp.status_code == 422


def test_invalid_rating_is_rejected(client: TestClient) -> None:
    resp = client.post(
        f"/coaching/{RESPONSE_ID}/feedback",
        json={"rating": "meh"},
        headers=_auth("user-1"),
    )
    assert resp.status_code == 422


def test_non_uuid_id_is_rejected(client: TestClient) -> None:
    resp = client.post(
        "/coaching/not-a-uuid/feedback", json={"rating": "up"}, headers=_auth("user-1")
    )
    assert resp.status_code == 422
