"""Tests for the /my-meals API + find_saved_meal (auth via dependency_overrides)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import my_meals
from backend.api.my_meals import IngredientIn, _totals, find_saved_meal
from backend.auth.supabase import get_current_user_id


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(my_meals.router)
    return app


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def _exec_returning(first):
    """A mock execute() result whose .scalars().first() returns `first`."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.first.return_value = first
    result.scalars.return_value = scalars
    return result


def test_totals_summed_server_side() -> None:
    ings = [
        IngredientIn(food_name="rice", qty_g=150, kcal=200, protein_g=4, carbs_g=44),
        IngredientIn(food_name="chicken", qty_g=120, kcal=250, protein_g=46, fat_g=6),
    ]
    t = _totals(ings)
    assert t["kcal"] == 450 and t["protein_g"] == 50 and t["carbs_g"] == 44
    assert t["fat_g"] == 6 and t["fiber_g"] == 0


def test_list_requires_auth() -> None:
    client = TestClient(_make_app())
    assert client.get("/my-meals").status_code == 401


def test_save_meal_rejects_duplicate_name() -> None:
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    client = TestClient(app)

    session = MagicMock()
    session.execute = AsyncMock(return_value=_exec_returning(MagicMock()))  # dup found
    factory = _mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.post(
            "/my-meals",
            json={
                "name": "Chicken Biryani",
                "ingredients": [{"food_name": "rice", "qty_g": 150, "kcal": 200}],
            },
        )
    assert resp.status_code == 409


def test_save_meal_empty_name_422() -> None:
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    client = TestClient(app)
    # Punctuation-only name normalizes to empty.
    resp = client.post(
        "/my-meals",
        json={"name": "!!!", "ingredients": [{"food_name": "rice", "qty_g": 150}]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_find_saved_meal_normalizes_and_matches() -> None:
    meal = MagicMock(name_normalized="chicken biryani")
    session = MagicMock()
    session.execute = AsyncMock(return_value=_exec_returning(meal))
    factory = _mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        found = await find_saved_meal("user-1", "  Chicken  Biryani! ")
    assert found is meal


@pytest.mark.asyncio
async def test_find_saved_meal_empty_text_returns_none() -> None:
    # Punctuation-only normalizes to empty → no DB call, returns None.
    with patch("backend.api.my_meals.get_session") as get_sess:
        found = await find_saved_meal("user-1", "...")
    assert found is None
    get_sess.assert_not_called()
