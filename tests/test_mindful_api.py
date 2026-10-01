"""API tests for GET /mindful/today (auth via dependency_overrides)."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.tools.mindful import NutrientAmount, SafetyAlert
from backend.api import mindful


def test_mindful_today_requires_auth(app_factory: Callable[..., FastAPI]) -> None:
    client = TestClient(app_factory(mindful.router, user_id=None))
    resp = client.get("/mindful/today")
    assert resp.status_code == 401


def test_mindful_today_returns_intake_and_alerts(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    client = TestClient(app_factory(mindful.router))

    goal = MagicMock(tracking_mode="mindful")
    factory = mock_session_factory(make_session(get_result=goal))

    nutrients = [
        NutrientAmount(name="Energy", amount=1840.0, unit="kcal"),
        NutrientAmount(name="Total Sugars", amount=58.0, unit="g"),
    ]
    alerts = [
        SafetyAlert(
            nutrient="Total Sugars",
            amount=58.0,
            limit=50.0,
            unit="g",
            source="WHO — Sugars intake for adults and children (2015)",
            url="https://www.who.int/x",
        )
    ]
    with (
        patch("backend.api.mindful.get_session", return_value=factory),
        patch(
            "backend.api.mindful.get_daily_intake",
            new=AsyncMock(return_value=nutrients),
        ),
        patch("backend.api.mindful.evaluate_safety", return_value=alerts),
    ):
        resp = client.get("/mindful/today")

    assert resp.status_code == 200
    body = resp.json()
    assert body["tracking_mode"] == "mindful"
    assert {n["name"] for n in body["nutrients"]} == {"Energy", "Total Sugars"}
    assert body["alerts"][0]["nutrient"] == "Total Sugars"
    assert body["alerts"][0]["url"].startswith("https://")
