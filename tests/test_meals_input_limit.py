from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import meals as meals_module
from backend.auth.supabase import get_current_user_id
from backend.ratelimit import RateLimitResult


@pytest.fixture
def handle() -> Iterator[AsyncMock]:
    """POST /meals/log with the orchestrator and rate limiter stubbed out."""
    mock = AsyncMock(return_value={"status": "success", "message": "ok"})
    with (
        patch.object(meals_module, "handle_message", mock),
        patch(
            "backend.ratelimit.check_rate_limit",
            AsyncMock(return_value=RateLimitResult(allowed=True, remaining=1)),
        ),
    ):
        yield mock


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(meals_module.router)
    app.state.checkpointer = MagicMock()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    return TestClient(app)


def test_message_at_the_cap_is_accepted(handle: AsyncMock) -> None:
    text = "a" * meals_module._MAX_USER_INPUT_CHARS

    resp = _client().post("/meals/log", json={"user_input": text})

    assert resp.status_code == 200
    assert handle.await_args.kwargs["user_input"] == text


def test_message_over_the_cap_is_rejected_before_any_model_call(
    handle: AsyncMock,
) -> None:
    text = "a" * (meals_module._MAX_USER_INPUT_CHARS + 1)

    resp = _client().post("/meals/log", json={"user_input": text})

    assert resp.status_code == 413
    assert "too long" in resp.json()["detail"]
    handle.assert_not_awaited()
