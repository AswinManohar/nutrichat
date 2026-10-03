"""Tests for the /my-meals API + find_saved_meal (auth via dependency_overrides)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from backend.api import my_meals
from backend.api.my_meals import (
    IngredientIn,
    _build_ingredients,
    _totals,
    find_saved_meal,
)
from tests.auth_helpers import DEFAULT_TEST_USER


@pytest.fixture(autouse=True)
def _stub_resolve_micros(monkeypatch: pytest.MonkeyPatch) -> None:
    """These API tests mock the DB session; keep spec 008's server-side micro
    resolution off the real estimate cache (all values unknown)."""
    from backend.nutrients.resolve import build_item_micros

    async def fake(fdc_id, food_name, qty_g, rejected=None):
        return build_item_micros({}, qty_g)

    monkeypatch.setattr("backend.api.my_meals.resolve_micros", fake)


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
    t = _totals(_build_ingredients(ings, 1.0))
    assert t["kcal"] == 450 and t["protein_g"] == 50 and t["carbs_g"] == 44
    assert t["fat_g"] == 6 and t["fiber_g"] == 0


def test_build_ingredients_scales_by_target_and_portion() -> None:
    item = IngredientIn(
        food_name="rice",
        qty_g=200,
        target_qty_g=100,
        kcal=260,
        protein_g=5,
        carbs_g=56,
        fat_g=1,
        fiber_g=2,
        nutrients={"iron": {"amount": 2.0, "unit": "mg"}},
    )
    (built,) = _build_ingredients([item], 2.0)  # scale = 100 * 2 / 200 = 1
    assert built["qty_g"] == 200
    assert built["kcal"] == 260 and built["fiber_g"] == 2
    assert "target_qty_g" not in built

    (half,) = _build_ingredients([item], 0.5)  # scale = 0.25
    assert half["qty_g"] == 50 and half["kcal"] == 65


def test_build_ingredients_no_target_portion_one_is_unchanged() -> None:
    item = IngredientIn(food_name="rice", qty_g=150, kcal=200, protein_g=4)
    (built,) = _build_ingredients([item], 1.0)
    assert built["qty_g"] == 150 and built["kcal"] == 200
    assert built["protein_g"] == 4 and built["carbs_g"] == 0.0


def test_build_ingredients_unknown_macro_stays_none() -> None:
    null_fiber = IngredientIn(food_name="a", qty_g=100, kcal=100, fiber_g=None)
    listed = IngredientIn(
        food_name="b",
        qty_g=100,
        target_qty_g=50,
        kcal=100,
        fiber_g=0.0,
        unknown_nutrients=["fiber_g"],
    )
    a, b = _build_ingredients([null_fiber, listed], 1.0)
    assert a["fiber_g"] is None
    assert b["fiber_g"] is None and b["unknown_nutrients"] == ["fiber_g"]
    assert _totals([a, b])["fiber_g"] == 0


def test_build_ingredients_extra_fields_pass_through() -> None:
    item = IngredientIn(
        food_name="rice",
        qty_g=100,
        kcal=100,
        unit="cup",
        source_dish="biryani",
        estimated=True,
        source="llm",
    )
    (built,) = _build_ingredients([item], 1.0)
    assert built["unit"] == "cup" and built["source_dish"] == "biryani"
    assert built["estimated"] is True and built["source"] == "llm"


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
    assert resp.json() == {"detail": "name_taken"}


def _post_save(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
    body: dict,
) -> tuple[object, list]:
    """POST /my-meals against a mocked session; return (response, added rows)."""
    client = TestClient(app_factory(my_meals.router))
    session = MagicMock()
    session.execute = AsyncMock(return_value=_exec_returning(None))  # no duplicate
    session.commit = AsyncMock()
    added: list = []
    session.add = MagicMock(side_effect=added.append)

    async def _refresh(meal: object) -> None:
        meal.updated_at = datetime(2026, 10, 1, tzinfo=UTC)  # type: ignore[attr-defined]

    session.refresh = AsyncMock(side_effect=_refresh)
    factory = mock_session_factory(session)
    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.post("/my-meals", json=body)
    return resp, added


def test_save_meal_applies_target_and_portion(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    resp, added = _post_save(
        app_factory,
        mock_session_factory,
        {
            "name": "Rice bowl",
            "portion": 1.5,
            "ingredients": [
                {
                    "food_name": "rice",
                    "qty_g": 200,
                    "target_qty_g": 150,
                    "kcal": 200,
                    "protein_g": 8,
                    "carbs_g": 40,
                    "fat_g": 4,
                    "fiber_g": 2,
                }
            ],
        },
    )
    assert resp.status_code == 201
    (ing,) = added[0].ingredients  # scale = 150 * 1.5 / 200 = 1.125
    assert ing["qty_g"] == 225
    assert ing["kcal"] == 225.0 and ing["protein_g"] == 9.0
    assert ing["carbs_g"] == 45.0 and ing["fat_g"] == 4.5
    assert added[0].kcal == 225.0 and added[0].fiber_g == 2.25
    assert resp.json()["ingredients"][0]["qty_g"] == 225


def test_save_meal_without_target_or_portion_is_unchanged(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    resp, added = _post_save(
        app_factory,
        mock_session_factory,
        {
            "name": "Legacy save",
            "ingredients": [
                {"food_name": "rice", "qty_g": 150, "kcal": 200, "protein_g": 4},
                {"food_name": "egg", "qty_g": 50, "kcal": 70, "fat_g": 5},
            ],
        },
    )
    assert resp.status_code == 201
    rice, egg = added[0].ingredients
    assert rice["qty_g"] == 150 and rice["kcal"] == 200 and rice["protein_g"] == 4
    assert egg["qty_g"] == 50 and egg["kcal"] == 70 and egg["fat_g"] == 5
    assert added[0].kcal == 270 and added[0].protein_g == 4 and added[0].fat_g == 5


def test_save_meal_unknown_fiber_stays_none(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    resp, added = _post_save(
        app_factory,
        mock_session_factory,
        {
            "name": "Mystery",
            "portion": 2,
            "ingredients": [
                {"food_name": "bar", "qty_g": 40, "kcal": 150, "fiber_g": None}
            ],
        },
    )
    assert resp.status_code == 201
    (ing,) = added[0].ingredients
    assert ing["fiber_g"] is None
    assert ing["kcal"] == 300
    assert added[0].fiber_g == 0


def test_get_meal_includes_updated_at(
    app_factory: Callable[..., FastAPI],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    client = TestClient(app_factory(my_meals.router))
    stamp = datetime(2026, 10, 1, 9, 12, 44, 123456, tzinfo=UTC)
    meal = MagicMock()
    meal.id = "meal-1"
    meal.user_id = DEFAULT_TEST_USER
    meal.name = "Biryani"
    meal.kcal = 500.0
    meal.protein_g = meal.carbs_g = meal.fat_g = meal.fiber_g = 1.0
    meal.ingredients = [{"food_name": "rice", "qty_g": 100}]
    meal.deleted_at = None
    meal.updated_at = stamp

    session = MagicMock()
    session.get = AsyncMock(return_value=meal)
    factory = mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.get("/my-meals/meal-1")

    assert resp.status_code == 200
    assert datetime.fromisoformat(resp.json()["updated_at"]) == stamp


def test_save_meal_empty_name_422(app_factory: Callable[..., FastAPI]) -> None:
    client = TestClient(app_factory(my_meals.router))
    # Punctuation-only name normalizes to empty.
    resp = client.post(
        "/my-meals",
        json={"name": "!!!", "ingredients": [{"food_name": "rice", "qty_g": 150}]},
    )
    assert resp.status_code == 422


async def test_find_saved_meal_normalizes_and_matches(
    mock_session_factory: Callable[[MagicMock], MagicMock],
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


# ---------------------------------------------------------------------------
# PUT /my-meals/{id}
# ---------------------------------------------------------------------------

_STAMP = datetime(2026, 10, 1, 9, 12, 44, 123456, tzinfo=UTC)


def _stored_meal(**overrides: object) -> MagicMock:
    meal = MagicMock()
    meal.id = "meal-1"
    meal.user_id = DEFAULT_TEST_USER
    meal.name = "Chicken Biryani"
    meal.name_normalized = "chicken biryani"
    meal.kcal = meal.protein_g = meal.carbs_g = meal.fat_g = meal.fiber_g = 1.0
    meal.ingredients = [{"food_name": "rice", "qty_g": 100, "kcal": 130}]
    meal.deleted_at = None
    meal.updated_at = _STAMP
    for key, value in overrides.items():
        setattr(meal, key, value)
    return meal


def _put_body(**overrides: object) -> dict:
    body: dict = {
        "name": "Biryani",
        "expected_updated_at": _STAMP.isoformat(),
        "ingredients": [
            {
                "food_name": "rice",
                "qty_g": 200,
                "target_qty_g": 100,
                "kcal": 260,
                "protein_g": 5,
                "carbs_g": 56,
                "fat_g": 1,
                "fiber_g": 2,
            },
            {"food_name": "chicken", "qty_g": 100, "kcal": 165, "protein_g": 31},
        ],
    }
    body.update(overrides)
    return body


def _put(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
    meal: object,
    body: dict,
    clash: object = None,
) -> tuple[object, MagicMock]:
    """PUT /my-meals/meal-1 against a mocked session; returns (response, session)."""
    session = make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_returning(meal), _exec_returning(clash)]
    )
    factory = mock_session_factory(session)
    client = TestClient(app_factory(my_meals.router))
    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.put("/my-meals/meal-1", json=body)
    return resp, session


def test_put_happy_path_recomputes_totals_and_bumps_updated_at(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    meal = _stored_meal()
    resp, session = _put(
        app_factory, make_session, mock_session_factory, meal, _put_body()
    )
    assert resp.status_code == 200
    data = resp.json()
    # rice 200 -> target 100 (half): 130 kcal; chicken 165.
    assert data["name"] == "Biryani" and data["n_ingredients"] == 2
    assert data["kcal"] == 295 and data["protein_g"] == 33.5
    assert meal.name == "Biryani" and meal.name_normalized == "biryani"
    assert meal.updated_at > _STAMP
    assert datetime.fromisoformat(data["updated_at"]) == meal.updated_at
    session.commit.assert_awaited_once()


def test_put_rejects_client_totals_and_never_stores_them(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    meal = _stored_meal()
    resp, _ = _put(
        app_factory,
        make_session,
        mock_session_factory,
        meal,
        _put_body(kcal=99999),
    )
    # extra="forbid" on the request: unknown top-level totals are rejected.
    assert resp.status_code == 422
    assert meal.kcal == 1.0


def test_put_target_qty_rescales_ingredient(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    meal = _stored_meal()
    resp, _ = _put(app_factory, make_session, mock_session_factory, meal, _put_body())
    assert resp.status_code == 200
    rice = meal.ingredients[0]
    assert rice["qty_g"] == 100 and rice["kcal"] == 130
    assert "target_qty_g" not in rice
    assert meal.fiber_g == 1.0  # 2 * 0.5 + 0 (chicken fiber default)


@pytest.mark.parametrize(
    "meal",
    [
        None,
        _stored_meal(deleted_at=_STAMP),
        _stored_meal(user_id="someone-else"),
    ],
    ids=["missing", "deleted", "other-user"],
)
def test_put_missing_deleted_or_foreign_meal_404(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
    meal: object,
) -> None:
    resp, session = _put(
        app_factory, make_session, mock_session_factory, meal, _put_body()
    )
    assert resp.status_code == 404
    session.commit.assert_not_awaited()


def test_put_name_taken_409(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    resp, session = _put(
        app_factory,
        make_session,
        mock_session_factory,
        _stored_meal(),
        _put_body(),
        clash="other-meal-id",
    )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "name_taken"}
    session.commit.assert_not_awaited()


def test_put_integrity_error_maps_to_name_taken(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    session = make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_returning(_stored_meal()), _exec_returning(None)]
    )
    session.commit = AsyncMock(side_effect=IntegrityError("x", {}, Exception()))
    session.rollback = AsyncMock()
    factory = mock_session_factory(session)
    client = TestClient(app_factory(my_meals.router))
    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.put("/my-meals/meal-1", json=_put_body())
    assert resp.status_code == 409
    assert resp.json() == {"detail": "name_taken"}


def test_put_same_name_different_case_allowed(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    # Renaming to a re-capitalized version of its own name finds no other meal.
    meal = _stored_meal()
    resp, _ = _put(
        app_factory,
        make_session,
        mock_session_factory,
        meal,
        _put_body(name="CHICKEN biryani"),
    )
    assert resp.status_code == 200
    assert meal.name == "CHICKEN biryani"
    assert meal.name_normalized == "chicken biryani"


def test_put_stale_expected_updated_at_409_meal_changed(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> None:
    meal = _stored_meal()
    stale = datetime(2026, 10, 1, 9, 12, 44, 123455, tzinfo=UTC).isoformat()
    resp, session = _put(
        app_factory,
        make_session,
        mock_session_factory,
        meal,
        _put_body(expected_updated_at=stale),
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "meal_changed"
    assert detail["current"]["name"] == "Chicken Biryani"
    assert datetime.fromisoformat(detail["current"]["updated_at"]) == _STAMP
    assert meal.name == "Chicken Biryani"
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        _put_body(name=""),
        _put_body(name="   "),
        _put_body(name="!!!"),
        _put_body(ingredients=[]),
        _put_body(ingredients=[{"food_name": "rice", "qty_g": 0}]),
        _put_body(ingredients=[{"food_name": "rice", "qty_g": 5, "target_qty_g": 0}]),
        _put_body(expected_updated_at="2026-10-01T09:12:44"),  # naive
    ],
    ids=[
        "empty-name",
        "blank-name",
        "punctuation-name",
        "no-ingredients",
        "qty-zero",
        "target-zero",
        "naive-timestamp",
    ],
)
def test_put_validation_422(
    app_factory: Callable[..., FastAPI],
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
    body: dict,
) -> None:
    resp, session = _put(
        app_factory, make_session, mock_session_factory, _stored_meal(), body
    )
    assert resp.status_code == 422
    session.commit.assert_not_awaited()


def test_put_requires_auth(app_factory: Callable[..., FastAPI]) -> None:
    client = TestClient(app_factory(my_meals.router, user_id=None))
    assert client.put("/my-meals/meal-1", json=_put_body()).status_code == 401
