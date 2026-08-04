"""Tests for GET /quota endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import quota as quota_router_module
from backend.auth.supabase import get_current_user_id
from backend.db.models import UserGoal


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(quota_router_module.router)
    return app


def _mock_goal(used: int, limit: int):
    goal = MagicMock()
    goal.llm_requests_used = used
    goal.llm_quota = limit
    return goal


def _mock_session(goal):
    session = MagicMock()
    session.get = AsyncMock(return_value=goal)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    # get_session() → factory, factory() → session (async ctx mgr)
    factory = MagicMock(return_value=session)
    return MagicMock(return_value=factory)


def test_quota_requires_auth():
    client = TestClient(_make_app())
    assert client.get("/quota").status_code == 401


def test_quota_free_user_under_limit(monkeypatch):
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    monkeypatch.setattr(quota_router_module, "get_session", _mock_session(_mock_goal(34, 50)))

    resp = TestClient(app).get("/quota")
    assert resp.status_code == 200
    assert resp.json() == {
        "used": 34, "limit": 50, "remaining": 16, "exhausted": False, "tier": "free"
    }


def test_quota_paid_user(monkeypatch):
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    monkeypatch.setattr(quota_router_module, "get_session", _mock_session(_mock_goal(80, 150)))

    resp = TestClient(app).get("/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "paid"
    assert body["remaining"] == 70
    assert body["exhausted"] is False


def test_quota_exhausted_user(monkeypatch):
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    monkeypatch.setattr(quota_router_module, "get_session", _mock_session(_mock_goal(50, 50)))

    resp = TestClient(app).get("/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body["exhausted"] is True
    assert body["remaining"] == 0


def test_quota_no_goal_row_returns_free_defaults(monkeypatch):
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "new-user"
    monkeypatch.setattr(quota_router_module, "get_session", _mock_session(None))

    resp = TestClient(app).get("/quota")
    assert resp.status_code == 200
    assert resp.json() == {
        "used": 0, "limit": 50, "remaining": 50, "exhausted": False, "tier": "free"
    }
