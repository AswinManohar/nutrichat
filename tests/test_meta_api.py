from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import meta


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(meta.router, user_id=None))


def test_meta_app_defaults(client: TestClient) -> None:
    resp = client.get("/meta/app")
    assert resp.status_code == 200
    assert resp.json() == {
        "min_supported_version_code": 1,
        "latest_version_code": 1,
    }


def test_meta_app_from_env(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANDROID_MIN_VERSION_CODE", "4")
    monkeypatch.setenv("ANDROID_LATEST_VERSION_CODE", "7")
    resp = client.get("/meta/app")
    assert resp.json() == {
        "min_supported_version_code": 4,
        "latest_version_code": 7,
    }


def test_meta_app_is_unauthed(client: TestClient) -> None:
    """No auth headers required — the route must not depend on get_current_user_id."""
    resp = client.get("/meta/app")
    assert resp.status_code == 200
