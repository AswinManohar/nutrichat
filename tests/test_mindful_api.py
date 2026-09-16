"""API tests for GET /mindful/today (auth via dependency_overrides)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.tools.mindful import NutrientAmount, SafetyAlert
from backend.api import mindful
from backend.auth.supabase import get_current_user_id


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mindful.router)
    return app


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def test_mindful_today_requires_auth() -> None:
    client = TestClient(_make_app())
    resp = client.get("/mindful/today")
    assert resp.status_code == 401


def test_mindful_today_returns_intake_and_alerts() -> None:
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    client = TestClient(app)

    goal = MagicMock(tracking_mode="mindful")
    session = MagicMock()
    session.get = AsyncMock(return_value=goal)
    factory = _mock_session_factory(session)

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
