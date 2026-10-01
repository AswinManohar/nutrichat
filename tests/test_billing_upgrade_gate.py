"""Tests for the BILLING_DEV_UPGRADE_ENABLED gate on POST /billing/upgrade."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import billing as billing_module
from backend.auth.supabase import get_current_user_id
from backend.quota import PAID_QUOTA


def _client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, MagicMock]:
    app = FastAPI()
    app.include_router(billing_module.router)
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
    return TestClient(app), session


@pytest.mark.parametrize("value", [None, "", "0", "false", "no"])
def test_upgrade_404_when_flag_off(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("BILLING_DEV_UPGRADE_ENABLED", raising=False)
    else:
        monkeypatch.setenv("BILLING_DEV_UPGRADE_ENABLED", value)
    client, session = _client(monkeypatch)

    resp = client.post("/billing/upgrade")

    assert resp.status_code == 404
    session.execute.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes"])
def test_upgrade_works_when_flag_on(monkeypatch, value):
    monkeypatch.setenv("BILLING_DEV_UPGRADE_ENABLED", value)
    client, session = _client(monkeypatch)

    resp = client.post("/billing/upgrade")

    assert resp.status_code == 200
    assert resp.json() == {"upgraded": True, "new_quota": PAID_QUOTA}
    session.execute.assert_called_once()
