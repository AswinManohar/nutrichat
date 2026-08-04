"""Tests for POST /billing/upgrade endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import billing as billing_module
from backend.auth.supabase import get_current_user_id
from backend.quota import PAID_QUOTA


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(billing_module.router)
    return app


def _mock_session(row):
    """Mock get_session() → factory, factory() → async ctx mgr with execute + commit."""
    result = MagicMock()
    result.fetchone.return_value = row

    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=session)
    return MagicMock(return_value=factory)


def test_upgrade_requires_auth():
    client = TestClient(_make_app())
    assert client.post("/billing/upgrade").status_code == 401


def test_upgrade_sets_paid_quota(monkeypatch):
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    monkeypatch.setattr(billing_module, "get_session", _mock_session((PAID_QUOTA,)))

    resp = TestClient(app).post("/billing/upgrade")
    assert resp.status_code == 200
    assert resp.json() == {"upgraded": True, "new_quota": PAID_QUOTA}


def test_upgrade_does_not_reset_usage(monkeypatch):
    """Verify execute is called without llm_requests_used in the SQL params."""
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    result = MagicMock()
    result.fetchone.return_value = (PAID_QUOTA,)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session)
    monkeypatch.setattr(billing_module, "get_session", MagicMock(return_value=factory))

    TestClient(app).post("/billing/upgrade")

    call_kwargs = session.execute.call_args[0][1]
    assert "llm_requests_used" not in call_kwargs


def test_upgrade_unboarded_user_returns_404(monkeypatch):
    """A user with no user_goal row (not yet onboarded) gets a 404."""
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "new-user"
    monkeypatch.setattr(billing_module, "get_session", _mock_session(None))

    resp = TestClient(app).post("/billing/upgrade")
    assert resp.status_code == 404
