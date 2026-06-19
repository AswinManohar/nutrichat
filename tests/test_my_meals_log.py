"""Tests for POST /my-meals/{id}/log — quick-log + customize scaling/validation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.tools.meals import MealLogResult
from backend.api import my_meals
from backend.auth.supabase import get_current_user_id


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(my_meals.router)
    return app


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def _stored(name: str, qty: float, kcal: float, na: float = 0.0) -> dict:
    return {
        "food_name": name,
        "qty_g": qty,
        "kcal": kcal,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "fiber_g": 0.0,
        "sugar_g": 0.0,
        "sat_fat_g": 0.0,
        "fdc_id": 123,
        "confidence": 0.9,
        "candidates": [],
        "source": "USDA",
        "estimated": False,
        "nutrients": {"Sodium, Na": {"amount": na, "unit": "mg"}},
    }


def _meal(user_id: str = "user-1", deleted: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id="meal-1",
        user_id=user_id,
        name="Chicken Biryani",
        deleted_at="2026-01-01" if deleted else None,
        ingredients=[
            _stored("rice", 150, 200, na=10.0),
            _stored("chicken", 120, 250, na=40.0),
        ],
    )


def _result() -> MealLogResult:
    return MealLogResult(
        meal_id="m1",
        meal_type="lunch",
        n_items=2,
        kcal=0,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        fiber_g=0,
        message="Logged",
    )


def _client_and_logmeal(meal):
    """Build an app with auth + mocked session/log_meal → (app, factory, logged)."""
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    session = MagicMock()
    session.get = AsyncMock(return_value=meal)
    factory = _mock_session_factory(session)
    logged = AsyncMock(return_value=_result())
    return app, factory, logged


def test_requires_auth() -> None:
    client = TestClient(_make_app())
    assert (
        client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"}).status_code
        == 401
    )


def test_quick_log_uses_stored_quantities() -> None:
    app, factory, logged = _client_and_logmeal(_meal())
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"})
    assert resp.status_code == 200
    results = logged.call_args.args[1]
    assert [r.qty_g for r in results] == [150, 120]
    assert [r.kcal for r in results] == [200, 250]  # scale == 1
    assert logged.call_args.args[2] == "lunch"
    assert logged.call_args.kwargs["label"] == "Chicken Biryani"


def test_portion_and_gram_override_scales_macros_and_nutrients() -> None:
    app, factory, logged = _client_and_logmeal(_meal())
    client = TestClient(app)
    # rice stored qty 150 → override 300 (2x) × portion 1.5 = scale 3x.
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post(
            "/my-meals/meal-1/log",
            json={
                "meal_type": "dinner",
                "portion": 1.5,
                "ingredients": [{"index": 0, "qty_g": 300}],
            },
        )
    assert resp.status_code == 200
    results = logged.call_args.args[1]
    assert len(results) == 1  # index 1 (chicken) removed
    r = results[0]
    assert r.qty_g == 450
    assert r.kcal == 600  # 200 × 3
    assert r.nutrients["Sodium, Na"].amount == 30.0  # 10 × 3


def test_removed_ingredient_excluded() -> None:
    app, factory, logged = _client_and_logmeal(_meal())
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post(
            "/my-meals/meal-1/log",
            json={"meal_type": "lunch", "ingredients": [{"index": 1, "qty_g": 120}]},
        )
    assert resp.status_code == 200
    results = logged.call_args.args[1]
    assert [r.food_name for r in results] == ["chicken"]


def test_other_users_meal_404() -> None:
    app, factory, logged = _client_and_logmeal(_meal(user_id="someone-else"))
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"})
    assert resp.status_code == 404
    logged.assert_not_called()


def test_deleted_meal_404() -> None:
    app, factory, logged = _client_and_logmeal(_meal(deleted=True))
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"})
    assert resp.status_code == 404


def test_missing_meal_404() -> None:
    app, factory, logged = _client_and_logmeal(None)
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"})
    assert resp.status_code == 404


def test_bad_meal_type_422() -> None:
    app, factory, logged = _client_and_logmeal(_meal())
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post(
            "/my-meals/meal-1/log", json={"meal_type": "second-breakfast"}
        )
    assert resp.status_code == 422


def test_portion_zero_422() -> None:
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    client = TestClient(app)
    resp = client.post(
        "/my-meals/meal-1/log", json={"meal_type": "lunch", "portion": 0}
    )
    assert resp.status_code == 422


def test_qty_zero_422() -> None:
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    client = TestClient(app)
    resp = client.post(
        "/my-meals/meal-1/log",
        json={"meal_type": "lunch", "ingredients": [{"index": 0, "qty_g": 0}]},
    )
    assert resp.status_code == 422


def test_all_removed_422() -> None:
    app, factory, logged = _client_and_logmeal(_meal())
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post(
            "/my-meals/meal-1/log", json={"meal_type": "lunch", "ingredients": []}
        )
    assert resp.status_code == 422
    logged.assert_not_called()
