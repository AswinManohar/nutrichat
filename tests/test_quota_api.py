"""Tests for GET /quota endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.api import quota as quota_router_module


def _mock_goal(used: int, limit: int):
    goal = MagicMock()
    goal.llm_requests_used = used
    goal.llm_quota = limit
    return goal


def test_quota_requires_auth(app_factory):
    client = TestClient(app_factory(quota_router_module.router, user_id=None))
    assert client.get("/quota").status_code == 401


def test_quota_free_user_under_limit(app_factory, make_session, patch_get_session):
    app = app_factory(quota_router_module.router, user_id="user-1")
    patch_get_session(quota_router_module, make_session(get_result=_mock_goal(34, 50)))

    resp = TestClient(app).get("/quota")
    assert resp.status_code == 200
    assert resp.json() == {
        "used": 34,
        "limit": 50,
        "remaining": 16,
        "exhausted": False,
        "tier": "free",
    }


def test_quota_paid_user(app_factory, make_session, patch_get_session):
    app = app_factory(quota_router_module.router, user_id="user-1")
    patch_get_session(quota_router_module, make_session(get_result=_mock_goal(80, 150)))

    resp = TestClient(app).get("/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "paid"
    assert body["remaining"] == 70
    assert body["exhausted"] is False


def test_quota_exhausted_user(app_factory, make_session, patch_get_session):
    app = app_factory(quota_router_module.router, user_id="user-1")
    patch_get_session(quota_router_module, make_session(get_result=_mock_goal(50, 50)))

    resp = TestClient(app).get("/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body["exhausted"] is True
    assert body["remaining"] == 0


def test_quota_no_goal_row_returns_free_defaults(
    app_factory, make_session, patch_get_session
):
    app = app_factory(quota_router_module.router, user_id="new-user")
    patch_get_session(quota_router_module, make_session(get_result=None))

    resp = TestClient(app).get("/quota")
    assert resp.status_code == 200
    assert resp.json() == {
        "used": 0,
        "limit": 50,
        "remaining": 50,
        "exhausted": False,
        "tier": "free",
    }
