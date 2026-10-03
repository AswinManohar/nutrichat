"""Tests for POST /my-meals/{id}/log — quick-log + customize scaling/validation."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.tools.meals import MealLogResult
from backend.api import my_meals


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


@pytest.fixture
def build_logmeal(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]]:
    """Return a builder: meal -> (app, factory, logged) with auth + mocks."""

    def build(meal: object) -> tuple[FastAPI, MagicMock, AsyncMock]:
        app = app_factory(my_meals.router)
        session = MagicMock()
        session.get = AsyncMock(return_value=meal)
        factory = mock_session_factory(session)
        logged = AsyncMock(return_value=_result())
        return app, factory, logged

    return build


def test_requires_auth(app_factory: Callable[..., FastAPI]) -> None:
    client = TestClient(app_factory(my_meals.router, user_id=None))
    assert (
        client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"}).status_code
        == 401
    )


def test_quick_log_uses_stored_quantities(
    build_logmeal: Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]],
) -> None:
    app, factory, logged = build_logmeal(_meal())
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


def test_portion_and_gram_override_scales_macros_and_nutrients(
    build_logmeal: Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]],
) -> None:
    app, factory, logged = build_logmeal(_meal())
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
    assert not hasattr(r, "nutrients")  # micros re-derived in log_meal (008)


def test_removed_ingredient_excluded(
    build_logmeal: Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]],
) -> None:
    app, factory, logged = build_logmeal(_meal())
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


def test_other_users_meal_404(
    build_logmeal: Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]],
) -> None:
    app, factory, logged = build_logmeal(_meal(user_id="someone-else"))
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"})
    assert resp.status_code == 404
    logged.assert_not_called()


def test_deleted_meal_404(
    build_logmeal: Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]],
) -> None:
    app, factory, logged = build_logmeal(_meal(deleted=True))
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"})
    assert resp.status_code == 404


def test_missing_meal_404(
    build_logmeal: Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]],
) -> None:
    app, factory, logged = build_logmeal(None)
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"})
    assert resp.status_code == 404


def test_bad_meal_type_422(
    build_logmeal: Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]],
) -> None:
    app, factory, logged = build_logmeal(_meal())
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post(
            "/my-meals/meal-1/log", json={"meal_type": "second-breakfast"}
        )
    assert resp.status_code == 422


def test_portion_zero_422(app_factory: Callable[..., FastAPI]) -> None:
    client = TestClient(app_factory(my_meals.router))
    resp = client.post(
        "/my-meals/meal-1/log", json={"meal_type": "lunch", "portion": 0}
    )
    assert resp.status_code == 422


def test_qty_zero_422(app_factory: Callable[..., FastAPI]) -> None:
    client = TestClient(app_factory(my_meals.router))
    resp = client.post(
        "/my-meals/meal-1/log",
        json={"meal_type": "lunch", "ingredients": [{"index": 0, "qty_g": 0}]},
    )
    assert resp.status_code == 422


def test_all_removed_422(
    build_logmeal: Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]],
) -> None:
    app, factory, logged = build_logmeal(_meal())
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


def test_log_stamps_saved_meal_id_flag_and_label(
    build_logmeal: Callable[[object], tuple[FastAPI, MagicMock, AsyncMock]],
) -> None:
    app, factory, logged = build_logmeal(_meal())
    client = TestClient(app)
    with (
        patch("backend.api.my_meals.get_session", return_value=factory),
        patch("backend.api.my_meals.log_meal", logged),
    ):
        resp = client.post("/my-meals/meal-1/log", json={"meal_type": "lunch"})
    assert resp.status_code == 200
    assert logged.call_args.kwargs["extra_flags"] == {"saved_meal_id": "meal-1"}
    assert logged.call_args.kwargs["label"] == "Chicken Biryani"


def _list_meal(meal_id: str, name: str) -> MagicMock:
    meal = MagicMock()
    meal.id = meal_id
    meal.name = name
    meal.name_normalized = name.lower()
    meal.kcal = meal.protein_g = meal.carbs_g = meal.fat_g = meal.fiber_g = 1.0
    meal.ingredients = ["x"]
    meal.deleted_at = None
    return meal


def _list_with_logs(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
    meals: list[MagicMock],
    log_rows: list[SimpleNamespace],
) -> dict[str, bool]:
    session = MagicMock()
    meals_result = MagicMock()
    meals_result.scalars.return_value.all.return_value = meals
    logs_result = MagicMock()
    logs_result.all.return_value = log_rows
    session.execute = AsyncMock(side_effect=[meals_result, logs_result])
    factory = mock_session_factory(session)
    client = TestClient(app_factory(my_meals.router))
    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.get("/my-meals")
    assert resp.status_code == 200
    return {m["id"]: m["logged_today"] for m in resp.json()}


def test_list_logged_today_via_flag_after_rename(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    # Logged as "Chicken Biryani", renamed to "Biryani" afterwards: the label no
    # longer matches but the saved_meal_id flag does.
    renamed = _list_meal("meal-1", "Biryani")
    other = _list_meal("meal-2", "Salad")
    rows = [SimpleNamespace(label="Chicken Biryani", saved_meal_id="meal-1")]
    flags = _list_with_logs(app_factory, mock_session_factory, [renamed, other], rows)
    assert flags == {"meal-1": True, "meal-2": False}


def test_list_logged_today_legacy_label_without_flag(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    meal = _list_meal("meal-1", "Chicken Biryani")
    rows = [
        SimpleNamespace(label="Chicken Biryani", saved_meal_id=None),
        SimpleNamespace(label=None, saved_meal_id=None),
    ]
    flags = _list_with_logs(app_factory, mock_session_factory, [meal], rows)
    assert flags == {"meal-1": True}
