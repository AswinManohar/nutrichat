"""Tests for POST /meals/log-items — direct (no-LLM) confirmation-card logging."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.tools.meals import MealLogResult
from backend.api import meals
from backend.auth.supabase import get_current_user_id


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(meals.router)
    return app


def _item(
    name: str,
    qty: float,
    target: float,
    kcal: float,
    na: float = 0.0,
    source_dish: str | None = None,
) -> dict:
    return {
        "food_name": name,
        "qty_g": qty,
        "target_qty_g": target,
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
        "source_dish": source_dish,
        "nutrients": {"Sodium, Na": {"amount": na, "unit": "mg"}},
    }


def _result() -> MealLogResult:
    return MealLogResult(
        meal_id="m1",
        meal_type="lunch",
        n_items=1,
        kcal=0,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        fiber_g=0,
        message="Logged",
    )


def _app_with_auth() -> tuple[FastAPI, AsyncMock]:
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    return app, AsyncMock(return_value=_result())


def test_requires_auth() -> None:
    client = TestClient(_make_app())
    resp = client.post(
        "/meals/log-items",
        json={"meal_type": "lunch", "items": [_item("rice", 150, 150, 200)]},
    )
    assert resp.status_code == 401


def test_logs_with_gram_and_portion_scaling() -> None:
    app, logged = _app_with_auth()
    client = TestClient(app)
    # rice base 150 → target 300 (2x) × portion 1.5 = 3x scale.
    with patch("backend.api.meals.persist_meal", logged):
        resp = client.post(
            "/meals/log-items",
            json={
                "meal_type": "dinner",
                "portion": 1.5,
                "items": [_item("rice", 150, 300, 200, na=10.0)],
            },
        )
    assert resp.status_code == 200
    results = logged.call_args.args[1]
    assert results[0].qty_g == 450
    assert results[0].kcal == 600  # 200 × 3
    assert results[0].nutrients["Sodium, Na"].amount == 30.0  # 10 × 3
    assert logged.call_args.args[2] == "dinner"


def test_label_prefers_source_dish() -> None:
    app, logged = _app_with_auth()
    client = TestClient(app)
    with patch("backend.api.meals.persist_meal", logged):
        resp = client.post(
            "/meals/log-items",
            json={
                "meal_type": "lunch",
                "items": [
                    _item("rice basmati", 120, 120, 150, source_dish="biryani"),
                    _item("chicken", 60, 60, 100, source_dish="biryani"),
                ],
            },
        )
    assert resp.status_code == 200
    assert logged.call_args.kwargs["label"] == "biryani"


def test_only_sent_items_logged() -> None:
    # The frontend drops removed items; the endpoint logs exactly what it gets.
    app, logged = _app_with_auth()
    client = TestClient(app)
    with patch("backend.api.meals.persist_meal", logged):
        resp = client.post(
            "/meals/log-items",
            json={"meal_type": "lunch", "items": [_item("chicken", 60, 60, 100)]},
        )
    assert resp.status_code == 200
    results = logged.call_args.args[1]
    assert [r.food_name for r in results] == ["chicken"]


def test_bad_meal_type_422() -> None:
    app, logged = _app_with_auth()
    client = TestClient(app)
    with patch("backend.api.meals.persist_meal", logged):
        resp = client.post(
            "/meals/log-items",
            json={"meal_type": "brinner", "items": [_item("rice", 150, 150, 200)]},
        )
    assert resp.status_code == 422
    logged.assert_not_called()


def test_empty_items_422() -> None:
    app, _ = _app_with_auth()
    client = TestClient(app)
    resp = client.post("/meals/log-items", json={"meal_type": "lunch", "items": []})
    assert resp.status_code == 422


def test_zero_target_qty_422() -> None:
    app, _ = _app_with_auth()
    client = TestClient(app)
    resp = client.post(
        "/meals/log-items",
        json={"meal_type": "lunch", "items": [_item("rice", 150, 0, 200)]},
    )
    assert resp.status_code == 422
