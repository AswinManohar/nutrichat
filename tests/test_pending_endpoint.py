"""GET /meals/pending returns the paused card or paused=false."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent import orchestrator
from backend.api import meals as meals_api

# Note: asyncio_mode = "auto" (pyproject.toml) runs async def tests without
# needing an explicit marker; the API-boundary tests below are sync
# (TestClient) and must not carry an asyncio mark.


async def test_not_paused_returns_false():
    graph = AsyncMock()
    graph.aget_state.return_value = SimpleNamespace(next=(), values={})
    with patch.object(orchestrator, "_graph_for", return_value=graph):
        out = await orchestrator.get_pending_card("u1", "t1", checkpointer=object())
    assert out == {"paused": False}


async def test_paused_returns_card():
    # usda_results entries are dicts (see _serialize_items / _handle_meal_logging),
    # not attribute-bearing objects.
    fake_result = {
        "fdc_id": 123,
        "food_name": "banana, raw",
        "qty_g": 118.0,
        "kcal": 105.0,
        "protein_g": 1.3,
        "carbs_g": 27.0,
        "fat_g": 0.4,
        "fiber_g": 3.1,
        "match_confidence": 0.95,
        "estimated": False,
    }

    class Msg:
        type = "ai"
        content = "Here's your card"

    graph = AsyncMock()
    graph.aget_state.return_value = SimpleNamespace(
        next=("intent_router",),
        values={"usda_results": [fake_result], "messages": [Msg()]},
    )
    with patch.object(orchestrator, "_graph_for", return_value=graph):
        out = await orchestrator.get_pending_card("u1", "t1", checkpointer=object())
    assert out["paused"] is True
    assert out["items"][0]["food_name"] == "banana, raw"
    assert out["message"] == "Here's your card"


# ---------------------------------------------------------------------------
# Thread-id namespacing at the API boundary (security fix, round 1).
#
# The checkpointer keys state on thread_id alone; user_id in config is only
# used by graph nodes at run time. Without server-side namespacing, one
# authenticated user could pass another user's conversation_id and read (or,
# on POST /meals/log, resume/confirm) that user's paused card. Both routes
# must namespace thread_id as f"{user_id}:{conversation_id}" before calling
# into the orchestrator.
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(meals_api.router)
    app.state.checkpointer = object()
    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    return TestClient(_make_app())


def test_pending_thread_id_namespaced_with_user_id(client: TestClient) -> None:
    with patch.object(
        meals_api, "get_pending_card", new=AsyncMock(return_value={"paused": False})
    ) as mock_get:
        resp = client.get(
            "/meals/pending?conversation_id=abc",
            headers={"X-Debug-User-Id": "user-1"},
        )
    assert resp.status_code == 200
    _, kwargs = mock_get.call_args
    assert kwargs["thread_id"] == "user-1:abc"
    assert kwargs["thread_id"].startswith("user-1:")


def test_pending_same_conversation_id_different_users_different_threads(
    client: TestClient,
) -> None:
    with patch.object(
        meals_api, "get_pending_card", new=AsyncMock(return_value={"paused": False})
    ) as mock_get:
        client.get(
            "/meals/pending?conversation_id=shared",
            headers={"X-Debug-User-Id": "user-1"},
        )
        thread_id_1 = mock_get.call_args.kwargs["thread_id"]

        client.get(
            "/meals/pending?conversation_id=shared",
            headers={"X-Debug-User-Id": "user-2"},
        )
        thread_id_2 = mock_get.call_args.kwargs["thread_id"]

    assert thread_id_1 != thread_id_2
    assert thread_id_1 == "user-1:shared"
    assert thread_id_2 == "user-2:shared"


def test_log_thread_id_namespaced_with_user_id(client: TestClient) -> None:
    with patch.object(
        meals_api,
        "handle_message",
        new=AsyncMock(
            return_value={"status": "success", "message": "", "paused": False, "items": []}
        ),
    ) as mock_handle:
        resp = client.post(
            "/meals/log",
            json={"user_input": "2 eggs", "conversation_id": "abc"},
            headers={"X-Debug-User-Id": "user-1"},
        )
    assert resp.status_code == 200
    kwargs = mock_handle.call_args.kwargs
    assert kwargs["thread_id"] == "user-1:abc"
    assert kwargs["thread_id"].startswith("user-1:")


def test_log_same_conversation_id_different_users_different_threads(
    client: TestClient,
) -> None:
    with patch.object(
        meals_api,
        "handle_message",
        new=AsyncMock(
            return_value={"status": "success", "message": "", "paused": False, "items": []}
        ),
    ) as mock_handle:
        client.post(
            "/meals/log",
            json={"user_input": "2 eggs", "conversation_id": "shared"},
            headers={"X-Debug-User-Id": "user-1"},
        )
        thread_id_1 = mock_handle.call_args.kwargs["thread_id"]

        client.post(
            "/meals/log",
            json={"user_input": "2 eggs", "conversation_id": "shared"},
            headers={"X-Debug-User-Id": "user-2"},
        )
        thread_id_2 = mock_handle.call_args.kwargs["thread_id"]

    assert thread_id_1 != thread_id_2
    assert thread_id_1 == "user-1:shared"
    assert thread_id_2 == "user-2:shared"


def test_log_default_conversation_id_reaches_same_thread_as_pending_default(
    client: TestClient,
) -> None:
    """No conversation_id on POST /meals/log must map to GET .../pending?conversation_id=default."""
    with patch.object(
        meals_api,
        "handle_message",
        new=AsyncMock(
            return_value={"status": "success", "message": "", "paused": False, "items": []}
        ),
    ) as mock_handle:
        client.post(
            "/meals/log",
            json={"user_input": "2 eggs"},
            headers={"X-Debug-User-Id": "user-1"},
        )
        log_thread_id = mock_handle.call_args.kwargs["thread_id"]

    with patch.object(
        meals_api, "get_pending_card", new=AsyncMock(return_value={"paused": False})
    ) as mock_get:
        client.get(
            "/meals/pending?conversation_id=default",
            headers={"X-Debug-User-Id": "user-1"},
        )
        pending_thread_id = mock_get.call_args.kwargs["thread_id"]

    assert log_thread_id == pending_thread_id == "user-1:default"
