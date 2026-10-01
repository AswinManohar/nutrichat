from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import meals as meals_api
from backend.db.redis_client import TodayTotals, get_today_totals
from tests.auth_helpers import with_header_auth

_USER = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# TodayTotals model
# ---------------------------------------------------------------------------


def test_today_totals_defaults_include_carbs_and_fat():
    totals = TodayTotals()
    assert totals.carbs_g == 0.0
    assert totals.fat_g == 0.0


# ---------------------------------------------------------------------------
# get_today_totals() — cold/rebuild path from Postgres
# ---------------------------------------------------------------------------


async def test_get_today_totals_includes_carbs_and_fat():
    result = MagicMock()
    result.one.return_value = (1500.0, 80.0, 150.0, 50.0, 20.0, 3)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session)

    with patch("backend.db.session.get_session", return_value=factory):
        totals = await get_today_totals(_USER)

    assert totals == TodayTotals(
        kcal=1500.0,
        protein_g=80.0,
        carbs_g=150.0,
        fat_g=50.0,
        fiber_g=20.0,
        n_meals=3,
    )


# ---------------------------------------------------------------------------
# GET /meals/today — by_type entries carry n_meals
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(meals_api.router)
    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    return TestClient(with_header_auth(_make_app()))


def test_by_type_counts_multiple_meals_of_same_type(client: TestClient) -> None:
    rows = [
        ("breakfast", [{"food_name": "eggs"}], 200.0),
        ("breakfast", [{"food_name": "toast"}], 150.0),
        ("lunch", [{"food_name": "salad"}], 300.0),
    ]
    result = MagicMock()
    result.all.return_value = rows
    db_session = MagicMock()
    db_session.execute = AsyncMock(return_value=result)
    db_session.__aenter__ = AsyncMock(return_value=db_session)
    db_session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=db_session)

    totals = TodayTotals(
        kcal=650.0, protein_g=40.0, carbs_g=60.0, fat_g=20.0, fiber_g=8.0, n_meals=3
    )

    with (
        patch("backend.api.meals.get_today_totals", AsyncMock(return_value=totals)),
        patch("backend.api.meals.get_session", return_value=factory),
    ):
        resp = client.get("/meals/today", headers={"X-Debug-User-Id": _USER})

    assert resp.status_code == 200
    body = resp.json()
    assert body["carbs_g"] == 60.0
    assert body["fat_g"] == 20.0

    by_type = {entry["meal_type"]: entry for entry in body["by_type"]}
    assert by_type["breakfast"]["n_meals"] == 2
    assert by_type["lunch"]["n_meals"] == 1
