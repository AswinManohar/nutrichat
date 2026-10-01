"""Tests for POST /billing/upgrade endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import billing as billing_module
from backend.quota import PAID_QUOTA


@pytest.fixture(autouse=True)
def _enable_dev_upgrade(monkeypatch):
    monkeypatch.setenv("BILLING_DEV_UPGRADE_ENABLED", "1")


def test_upgrade_requires_auth(app_factory):
    client = TestClient(app_factory(billing_module.router, user_id=None))
    assert client.post("/billing/upgrade").status_code == 401


def test_upgrade_sets_paid_quota(app_factory, make_session, patch_get_session):
    app = app_factory(billing_module.router)
    patch_get_session(billing_module, make_session(execute_row=(PAID_QUOTA,)))

    resp = TestClient(app).post("/billing/upgrade")
    assert resp.status_code == 200
    assert resp.json() == {"upgraded": True, "new_quota": PAID_QUOTA}


def test_upgrade_does_not_reset_usage(app_factory, make_session, patch_get_session):
    """Verify execute is called without llm_requests_used in the SQL params."""
    app = app_factory(billing_module.router)
    session = patch_get_session(billing_module, make_session(execute_row=(PAID_QUOTA,)))

    TestClient(app).post("/billing/upgrade")

    call_kwargs = session.execute.call_args[0][1]
    assert "llm_requests_used" not in call_kwargs


def test_upgrade_unboarded_user_returns_404(
    app_factory, make_session, patch_get_session
):
    """A user with no user_goal row (not yet onboarded) gets a 404."""
    app = app_factory(billing_module.router, user_id="new-user")
    patch_get_session(billing_module, make_session(execute_row=None))

    resp = TestClient(app).post("/billing/upgrade")
    assert resp.status_code == 404
