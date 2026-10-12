from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.memory import (
    ApplyOutcome,
    MemoryFact,
    OpResult,
    ProfileState,
    RemoveFact,
)
from backend.api import memory
from backend.ratelimit import RateLimitResult

FACT_ID = "3f7c1a2e-9b4d-4c8e-8f1a-2b3c4d5e6f70"


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(memory.router, header_auth=True))


@pytest.fixture
def anon_client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(memory.router, user_id=None))


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


def _apply(applied: bool) -> AsyncMock:
    async def fake(user_id, ops, actor):
        return ApplyOutcome(results=[OpResult(op=ops[0], applied=applied)])

    return AsyncMock(side_effect=fake)


def test_get_memory_returns_facts_settings_and_staples(client: TestClient) -> None:
    state = ProfileState(
        facts=[
            MemoryFact(
                id=FACT_ID,
                fact="Allergic to peanuts",
                kind="restriction",
                source="stated",
            )
        ],
        tombstones=["Likes spicy food"],
        diet_chips=["vegetarian"],
    )
    load = AsyncMock(return_value=state)
    with (
        patch("backend.api.memory.load_state", load),
        patch(
            "backend.api.memory.fetch_staples",
            AsyncMock(return_value={"breakfast": ["Oats"]}),
        ),
        patch("backend.api.memory.profile_active", return_value=True),
    ):
        response = client.get("/memory", headers=_auth("user-a"))

    assert response.status_code == 200
    load.assert_awaited_once_with("user-a")
    body = response.json()
    assert body == {
        "coach_uses_profile": True,
        "facts": [
            {
                "id": FACT_ID,
                "fact": "Allergic to peanuts",
                "kind": "restriction",
                "source": "stated",
                "updated_at": None,
            }
        ],
        "diet_settings": ["vegetarian"],
        "staples": {"breakfast": ["Oats"]},
    }
    # Removed facts are never sent back to the client.
    assert "Likes spicy food" not in response.text


def test_delete_fact_tombstones_as_the_user(client: TestClient) -> None:
    apply = _apply(True)
    with patch("backend.api.memory.apply_ops", apply):
        response = client.delete(f"/memory/{FACT_ID}", headers=_auth("user-a"))

    assert response.status_code == 204
    apply.assert_awaited_once_with("user-a", [RemoveFact(id=FACT_ID)], "user")


def test_delete_unknown_or_foreign_fact_is_404(client: TestClient) -> None:
    # apply_ops only ever loads the caller's rows, so another user's fact id
    # is indistinguishable from an unknown one.
    with patch("backend.api.memory.apply_ops", _apply(False)):
        response = client.delete(f"/memory/{FACT_ID}", headers=_auth("user-b"))

    assert response.status_code == 404


def test_delete_rejects_a_malformed_id(client: TestClient) -> None:
    apply = _apply(True)
    with patch("backend.api.memory.apply_ops", apply):
        response = client.delete("/memory/not-a-uuid", headers=_auth("user-a"))

    assert response.status_code == 422
    apply.assert_not_awaited()


def test_memory_endpoints_require_auth(anon_client: TestClient) -> None:
    assert anon_client.get("/memory").status_code == 401
    assert anon_client.delete(f"/memory/{FACT_ID}").status_code == 401
