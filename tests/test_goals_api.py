from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import goals
from backend.db.models import UserGoal


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(goals.router, header_auth=True))


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Debug-User-Id": user_id}


def test_get_goals_404_before_onboarding(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    factory = mock_session_factory(session)

    with patch("backend.api.goals.get_session", return_value=factory):
        resp = client.get("/goals", headers=_auth_headers("user-1"))

    assert resp.status_code == 404


def test_post_then_get_goals_round_trips(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    store: dict[str, UserGoal] = {}

    session = MagicMock()

    async def fake_get(model, user_id):
        return store.get(user_id)

    def fake_add(goal):
        store[goal.user_id] = goal

    async def fake_commit():
        pass

    async def fake_refresh(goal):
        pass

    session.get = fake_get
    session.add = fake_add
    session.commit = fake_commit
    session.refresh = fake_refresh
    factory = mock_session_factory(session)

    with patch("backend.api.goals.get_session", return_value=factory):
        post_resp = client.post(
            "/goals",
            json={
                "kcal_goal": 2000,
                "protein_goal": 150,
                "fiber_goal": 30,
                "dietary_prefs": {},
            },
            headers=_auth_headers("user-1"),
        )
        assert post_resp.status_code == 201

        get_resp = client.get("/goals", headers=_auth_headers("user-1"))
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["kcal_goal"] == 2000
        assert body["protein_goal"] == 150
        assert body["fiber_goal"] == 30


def test_post_goals_conflict_if_already_onboarded(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    existing = UserGoal(
        user_id="user-1",
        kcal_goal=2000,
        protein_goal=150,
        fiber_goal=30,
        dietary_prefs={},
        streak_days=0,
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=existing)
    factory = mock_session_factory(session)

    with patch("backend.api.goals.get_session", return_value=factory):
        resp = client.post(
            "/goals",
            json={
                "kcal_goal": 2000,
                "protein_goal": 150,
                "fiber_goal": 30,
                "dietary_prefs": {},
            },
            headers=_auth_headers("user-1"),
        )

    assert resp.status_code == 409


def test_put_goals_updates_existing(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    existing = UserGoal(
        user_id="user-1",
        kcal_goal=2000,
        protein_goal=150,
        fiber_goal=30,
        dietary_prefs={},
        streak_days=2,
    )

    session = MagicMock()
    session.get = AsyncMock(return_value=existing)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    factory = mock_session_factory(session)

    with patch("backend.api.goals.get_session", return_value=factory):
        resp = client.put(
            "/goals",
            json={
                "kcal_goal": 2200,
                "protein_goal": 160,
                "fiber_goal": 35,
                "dietary_prefs": {"vegan": True},
            },
            headers=_auth_headers("user-1"),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["kcal_goal"] == 2200
    assert body["protein_goal"] == 160
    assert body["fiber_goal"] == 35
    assert body["dietary_prefs"] == {"vegan": True}


def test_put_goals_mindful_preserves_targets(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    """Switching to mindful mode without targets must not null them out,
    and switching back to goals mode must restore the preserved values.
    """
    existing = UserGoal(
        user_id="user-1",
        tracking_mode="goals",
        kcal_goal=2200,
        protein_goal=110,
        fiber_goal=31,
        dietary_prefs={},
        streak_days=2,
    )

    session = MagicMock()
    session.get = AsyncMock(return_value=existing)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    factory = mock_session_factory(session)

    with patch("backend.api.goals.get_session", return_value=factory):
        mindful_resp = client.put(
            "/goals",
            json={"tracking_mode": "mindful", "dietary_prefs": {}},
            headers=_auth_headers("user-1"),
        )

        assert mindful_resp.status_code == 200
        mindful_body = mindful_resp.json()
        assert mindful_body["tracking_mode"] == "mindful"
        assert mindful_body["kcal_goal"] == 2200
        assert mindful_body["protein_goal"] == 110
        assert mindful_body["fiber_goal"] == 31

        goals_resp = client.put(
            "/goals",
            json={
                "tracking_mode": "goals",
                "kcal_goal": 2200,
                "protein_goal": 110,
                "fiber_goal": 31,
                "dietary_prefs": {},
            },
            headers=_auth_headers("user-1"),
        )

    assert goals_resp.status_code == 200
    goals_body = goals_resp.json()
    assert goals_body["kcal_goal"] == 2200
    assert goals_body["protein_goal"] == 110
    assert goals_body["fiber_goal"] == 31


def test_put_goals_404_before_onboarding(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    factory = mock_session_factory(session)

    with patch("backend.api.goals.get_session", return_value=factory):
        resp = client.put(
            "/goals",
            json={
                "kcal_goal": 2000,
                "protein_goal": 150,
                "fiber_goal": 30,
                "dietary_prefs": {},
            },
            headers=_auth_headers("user-1"),
        )

    assert resp.status_code == 404


def test_goals_isolated_between_users(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    store: dict[str, UserGoal] = {
        "user-1": UserGoal(
            user_id="user-1",
            kcal_goal=2000,
            protein_goal=150,
            fiber_goal=30,
            dietary_prefs={},
            streak_days=0,
        )
    }

    session = MagicMock()

    async def fake_get(model, user_id):
        return store.get(user_id)

    session.get = fake_get
    factory = mock_session_factory(session)

    with patch("backend.api.goals.get_session", return_value=factory):
        resp_1 = client.get("/goals", headers=_auth_headers("user-1"))
        resp_2 = client.get("/goals", headers=_auth_headers("user-2"))

    assert resp_1.status_code == 200
    assert resp_2.status_code == 404


def test_get_goals_requires_auth(
    monkeypatch: pytest.MonkeyPatch, app_factory: Callable[..., FastAPI]
) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    client = TestClient(app_factory(goals.router, user_id=None))

    resp = client.get("/goals")
    assert resp.status_code == 401


def _round_trip_session(
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> tuple[MagicMock, dict[str, UserGoal]]:
    store: dict[str, UserGoal] = {}
    session = MagicMock()

    async def fake_get(model, user_id):
        return store.get(user_id)

    def fake_add(goal):
        store[goal.user_id] = goal

    async def noop(*_args):
        pass

    session.get = fake_get
    session.add = fake_add
    session.commit = noop
    session.refresh = noop
    return mock_session_factory(session), store


def test_conditions_round_trip_through_post_put_get(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    factory, _ = _round_trip_session(mock_session_factory)
    base = {
        "kcal_goal": 2000,
        "protein_goal": 150,
        "fiber_goal": 30,
        "dietary_prefs": {},
    }

    with patch("backend.api.goals.get_session", return_value=factory):
        post = client.post(
            "/goals",
            json={**base, "conditions": ["prediabetes"]},
            headers=_auth_headers("user-1"),
        )
        assert post.status_code == 201
        assert post.json()["conditions"] == ["prediabetes"]

        put = client.put(
            "/goals",
            json={**base, "conditions": ["diabetes", "hypertension"]},
            headers=_auth_headers("user-1"),
        )
        assert put.status_code == 200

        get = client.get("/goals", headers=_auth_headers("user-1"))
        assert get.json()["conditions"] == ["diabetes", "hypertension"]


def test_conditions_default_to_empty_list(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    factory, _ = _round_trip_session(mock_session_factory)
    with patch("backend.api.goals.get_session", return_value=factory):
        post = client.post(
            "/goals",
            json={"kcal_goal": 2000, "protein_goal": 150, "fiber_goal": 30},
            headers=_auth_headers("user-1"),
        )
    assert post.status_code == 201
    assert post.json()["conditions"] == []


def test_invalid_condition_is_rejected(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    factory, _ = _round_trip_session(mock_session_factory)
    with patch("backend.api.goals.get_session", return_value=factory):
        resp = client.put(
            "/goals",
            json={
                "kcal_goal": 2000,
                "protein_goal": 150,
                "fiber_goal": 30,
                "conditions": ["gout"],
            },
            headers=_auth_headers("user-1"),
        )
    assert resp.status_code == 422


def test_put_without_conditions_leaves_them_unchanged(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    factory, store = _round_trip_session(mock_session_factory)
    base = {"kcal_goal": 2000, "protein_goal": 150, "fiber_goal": 30}

    with patch("backend.api.goals.get_session", return_value=factory):
        client.post(
            "/goals",
            json={**base, "conditions": ["diabetes"]},
            headers=_auth_headers("user-1"),
        )
        put = client.put("/goals", json=base, headers=_auth_headers("user-1"))

    assert put.status_code == 200
    assert put.json()["conditions"] == ["diabetes"]
    assert store["user-1"].conditions == ["diabetes"]


def test_put_with_empty_conditions_clears_them(
    client: TestClient, mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    factory, store = _round_trip_session(mock_session_factory)
    base = {"kcal_goal": 2000, "protein_goal": 150, "fiber_goal": 30}

    with patch("backend.api.goals.get_session", return_value=factory):
        client.post(
            "/goals",
            json={**base, "conditions": ["diabetes"]},
            headers=_auth_headers("user-1"),
        )
        put = client.put(
            "/goals", json={**base, "conditions": []}, headers=_auth_headers("user-1")
        )

    assert put.status_code == 200
    assert put.json()["conditions"] == []
    assert store["user-1"].conditions == []
