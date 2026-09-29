from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import goals
from backend.db.models import UserGoal


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(goals.router)
    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    return TestClient(_make_app())


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Debug-User-Id": user_id}


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def test_get_goals_404_before_onboarding(client: TestClient) -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    factory = _mock_session_factory(session)

    with patch("backend.api.goals.get_session", return_value=factory):
        resp = client.get("/goals", headers=_auth_headers("user-1"))

    assert resp.status_code == 404


def test_post_then_get_goals_round_trips(client: TestClient) -> None:
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
    factory = _mock_session_factory(session)

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


def test_post_goals_conflict_if_already_onboarded(client: TestClient) -> None:
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
    factory = _mock_session_factory(session)

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


def test_put_goals_updates_existing(client: TestClient) -> None:
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
    factory = _mock_session_factory(session)

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


def test_put_goals_mindful_preserves_targets(client: TestClient) -> None:
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
    factory = _mock_session_factory(session)

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


def test_put_goals_404_before_onboarding(client: TestClient) -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    factory = _mock_session_factory(session)

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


def test_goals_isolated_between_users(client: TestClient) -> None:
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
    factory = _mock_session_factory(session)

    with patch("backend.api.goals.get_session", return_value=factory):
        resp_1 = client.get("/goals", headers=_auth_headers("user-1"))
        resp_2 = client.get("/goals", headers=_auth_headers("user-2"))

    assert resp_1.status_code == 200
    assert resp_2.status_code == 404


def test_get_goals_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV_BYPASS_AUTH", raising=False)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    client = TestClient(_make_app())

    resp = client.get("/goals")
    assert resp.status_code == 401


def _round_trip_session() -> tuple[MagicMock, dict[str, UserGoal]]:
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
    return _mock_session_factory(session), store


def test_conditions_round_trip_through_post_put_get(client: TestClient) -> None:
    factory, _ = _round_trip_session()
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


def test_conditions_default_to_empty_list(client: TestClient) -> None:
    factory, _ = _round_trip_session()
    with patch("backend.api.goals.get_session", return_value=factory):
        post = client.post(
            "/goals",
            json={"kcal_goal": 2000, "protein_goal": 150, "fiber_goal": 30},
            headers=_auth_headers("user-1"),
        )
    assert post.status_code == 201
    assert post.json()["conditions"] == []


def test_invalid_condition_is_rejected(client: TestClient) -> None:
    factory, _ = _round_trip_session()
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


def test_put_without_conditions_leaves_them_unchanged(client: TestClient) -> None:
    factory, store = _round_trip_session()
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


def test_put_with_empty_conditions_clears_them(client: TestClient) -> None:
    factory, store = _round_trip_session()
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
