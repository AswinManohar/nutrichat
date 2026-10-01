"""Tests for the /my-meals API + find_saved_meal (auth via dependency_overrides)."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import my_meals
from backend.api.my_meals import IngredientIn, _totals, find_saved_meal


def _exec_returning(first):
    """A mock execute() result whose .scalars().first() returns `first`."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.first.return_value = first
    result.scalars.return_value = scalars
    return result


def _exec_returning_all(rows: list):
    """A mock execute() result whose .scalars().all() returns `rows`."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


def _exec_returning_rows(rows: list):
    """A mock execute() result whose .all() returns `rows` (non-scalar)."""
    result = MagicMock()
    result.all.return_value = rows
    return result


def test_totals_summed_server_side() -> None:
    ings = [
        IngredientIn(food_name="rice", qty_g=150, kcal=200, protein_g=4, carbs_g=44),
        IngredientIn(food_name="chicken", qty_g=120, kcal=250, protein_g=46, fat_g=6),
    ]
    t = _totals(ings)
    assert t["kcal"] == 450 and t["protein_g"] == 50 and t["carbs_g"] == 44
    assert t["fat_g"] == 6 and t["fiber_g"] == 0


def test_list_requires_auth(app_factory: Callable[..., FastAPI]) -> None:
    client = TestClient(app_factory(my_meals.router, user_id=None))
    assert client.get("/my-meals").status_code == 401


def test_save_meal_rejects_duplicate_name(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    client = TestClient(app_factory(my_meals.router))

    session = MagicMock()
    session.execute = AsyncMock(return_value=_exec_returning(MagicMock()))  # dup found
    factory = mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.post(
            "/my-meals",
            json={
                "name": "Chicken Biryani",
                "ingredients": [{"food_name": "rice", "qty_g": 150, "kcal": 200}],
            },
        )
    assert resp.status_code == 409


def test_save_meal_empty_name_422(app_factory: Callable[..., FastAPI]) -> None:
    client = TestClient(app_factory(my_meals.router))
    # Punctuation-only name normalizes to empty.
    resp = client.post(
        "/my-meals",
        json={"name": "!!!", "ingredients": [{"food_name": "rice", "qty_g": 150}]},
    )
    assert resp.status_code == 422


async def test_find_saved_meal_normalizes_and_matches(
    mock_session_factory: Callable[[MagicMock], MagicMock]
) -> None:
    meal = MagicMock(name_normalized="chicken biryani")
    session = MagicMock()
    session.execute = AsyncMock(return_value=_exec_returning_all([meal]))
    factory = mock_session_factory(session)

    with patch("backend.agent.tools.saved_meals.get_session", return_value=factory):
        found = await find_saved_meal("user-1", "  Chicken  Biryani! ")
    assert found is meal


async def test_find_saved_meal_empty_text_returns_none() -> None:
    # Punctuation-only normalizes to empty → no DB call, returns None.
    with patch("backend.api.my_meals.get_session") as get_sess:
        found = await find_saved_meal("user-1", "...")
    assert found is None
    get_sess.assert_not_called()


def test_list_meals_logged_today_true(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    """A saved meal whose name matches a today label gets logged_today=True."""
    client = TestClient(app_factory(my_meals.router))

    meal = MagicMock()
    meal.id = "meal-1"
    meal.name = "Chicken Biryani"
    meal.name_normalized = "chicken biryani"
    meal.kcal = 500.0
    meal.protein_g = 30.0
    meal.carbs_g = 60.0
    meal.fat_g = 10.0
    meal.fiber_g = 3.0
    meal.ingredients = ["ing1", "ing2"]
    meal.deleted_at = None

    session = MagicMock()
    # First call: list saved meals
    # Second call: today's logged labels
    label_row = MagicMock()
    label_row.label = "Chicken Biryani"
    session.execute = AsyncMock(
        side_effect=[
            _exec_returning_all([meal]),
            _exec_returning_rows([label_row]),
        ]
    )
    factory = mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.get("/my-meals")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["logged_today"] is True


def test_list_meals_logged_today_false(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    """A saved meal with no matching today label gets logged_today=False."""
    client = TestClient(app_factory(my_meals.router))

    meal = MagicMock()
    meal.id = "meal-2"
    meal.name = "Oat Porridge"
    meal.name_normalized = "oat porridge"
    meal.kcal = 300.0
    meal.protein_g = 10.0
    meal.carbs_g = 50.0
    meal.fat_g = 5.0
    meal.fiber_g = 6.0
    meal.ingredients = ["oats"]
    meal.deleted_at = None

    session = MagicMock()
    # Today's labels contain a different meal
    label_row = MagicMock()
    label_row.label = "Chicken Biryani"
    session.execute = AsyncMock(
        side_effect=[
            _exec_returning_all([meal]),
            _exec_returning_rows([label_row]),
        ]
    )
    factory = mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.get("/my-meals")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["logged_today"] is False


def test_list_meals_no_logs_today(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    """When no meals are logged today, all saved meals get logged_today=False."""
    client = TestClient(app_factory(my_meals.router))

    meal = MagicMock()
    meal.id = "meal-3"
    meal.name = "Salad"
    meal.name_normalized = "salad"
    meal.kcal = 150.0
    meal.protein_g = 5.0
    meal.carbs_g = 10.0
    meal.fat_g = 8.0
    meal.fiber_g = 4.0
    meal.ingredients = ["lettuce"]
    meal.deleted_at = None

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _exec_returning_all([meal]),
            _exec_returning_rows([]),  # no labels today
        ]
    )
    factory = mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.get("/my-meals")

    assert resp.status_code == 200
    assert resp.json()[0]["logged_today"] is False
