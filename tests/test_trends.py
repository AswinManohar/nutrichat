from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api import meals as meals_api
from backend.agent.tools.meals import _is_junk, _junk_flags
from backend.auth.supabase import get_current_user_id

_USER = "00000000-0000-0000-0000-000000000001"


def _result(
    qty_g: float, sugar_g: float, sat_fat_g: float, fiber_g: float, name="food"
):
    r = MagicMock()
    r.qty_g = qty_g
    r.sugar_g = sugar_g
    r.sat_fat_g = sat_fat_g
    r.fiber_g = fiber_g
    r.food_name = name
    return r


def test_soda_is_junk():
    # Cola: ~10.6g sugar/100g, no fiber, no sat fat
    assert _is_junk(_result(qty_g=355, sugar_g=39.0, sat_fat_g=0.0, fiber_g=0.0))


def test_banana_is_not_junk():
    # Banana: ~12g sugar/100g but fiber-rich (2.6g/100g) → fiber floor saves it
    assert not _is_junk(_result(qty_g=118, sugar_g=14.4, sat_fat_g=0.13, fiber_g=3.07))


def test_butter_is_junk_via_sat_fat():
    # Butter: ~51g sat fat/100g
    assert _is_junk(_result(qty_g=14, sugar_g=0.01, sat_fat_g=7.2, fiber_g=0.0))


def test_chicken_breast_is_not_junk():
    assert not _is_junk(_result(qty_g=150, sugar_g=0.0, sat_fat_g=1.5, fiber_g=0.0))


def test_junk_flags_payload():
    flags = _junk_flags(
        [
            _result(355, 39.0, 0.0, 0.0, name="Cola"),
            _result(150, 0.0, 1.5, 0.0, name="Chicken breast"),
        ]
    )
    assert flags == {"has_junk": True, "junk_items": ["Cola"]}


def test_junk_flags_clean_meal():
    flags = _junk_flags([_result(150, 0.0, 1.5, 0.0, name="Chicken breast")])
    assert flags == {"has_junk": False, "junk_items": []}


# ---------------------------------------------------------------------------
# GET /meals/trends
# ---------------------------------------------------------------------------


def _override_user(request: Request) -> str:
    """Resolve the test user from the X-Debug-User-Id header (auth override)."""
    return request.headers.get("X-Debug-User-Id", "user-1")


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(meals_api.router)
    app.dependency_overrides[get_current_user_id] = _override_user
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app())


def test_trends_returns_day_aggregates(client: TestClient) -> None:
    row = MagicMock(
        day=date(2026, 6, 10),
        kcal=1500.0,
        protein_g=80.0,
        fiber_g=20.0,
        n_meals=3,
        junk_meals=1,
    )
    result = MagicMock()
    result.all.return_value = [row]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session)

    with patch("backend.api.meals.get_session", return_value=factory):
        resp = client.get("/meals/trends?days=30", headers={"X-Debug-User-Id": _USER})

    assert resp.status_code == 200
    body = resp.json()
    assert body == [
        {
            "date": "2026-06-10",
            "kcal": 1500.0,
            "protein_g": 80.0,
            "fiber_g": 20.0,
            "n_meals": 3,
            "junk_meals": 1,
        }
    ]


def test_trends_rejects_bad_days(client: TestClient) -> None:
    resp = client.get("/meals/trends?days=0", headers={"X-Debug-User-Id": _USER})
    assert resp.status_code == 422
