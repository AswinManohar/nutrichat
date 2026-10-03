"""Tests for GET /meals/log (list) and GET /meals/log/{meal_id} (detail)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import meals as meals_api

_USER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(meals_api.router, user_id=_USER))


def _mock_row(
    meal_id: str = "meal-1",
    meal_type: str = "breakfast",
    logged_at: datetime = datetime(2026, 9, 16, 8, 0, tzinfo=UTC),
    label: str | None = "Eggs on toast",
    kcal: float = 350.0,
    protein_g: float = 20.0,
    carbs_g: float = 30.0,
    fat_g: float = 10.0,
    fiber_g: float = 4.0,
    entities: list | str | None = None,
) -> MagicMock:
    row = MagicMock()
    row.meal_id = meal_id
    row.meal_type = meal_type
    row.logged_at = logged_at
    row.label = label
    row.kcal = kcal
    row.protein_g = protein_g
    row.carbs_g = carbs_g
    row.fat_g = fat_g
    row.fiber_g = fiber_g
    row.entities = entities if entities is not None else [{"food_name": "eggs"}]
    row.micros = {}  # spec 008: meal-level summary column
    return row


@pytest.fixture
def session_returning_scalars(
    make_session: Callable[..., MagicMock],
) -> Callable[[list], MagicMock]:
    """Build a session mock whose execute().scalars().all() returns rows."""

    def build(rows: list) -> MagicMock:
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = rows
        result.scalars.return_value = scalars
        session = make_session()
        session.execute = AsyncMock(return_value=result)
        return session

    return build


@pytest.fixture
def session_returning_scalar_one(
    make_session: Callable[..., MagicMock],
) -> Callable[[object], MagicMock]:
    """Build a session mock whose execute().scalar_one_or_none() returns row."""

    def build(row: object) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        session = make_session()
        session.execute = AsyncMock(return_value=result)
        return session

    return build


# ---------------------------------------------------------------------------
# GET /meals/log — list
# ---------------------------------------------------------------------------


def test_list_returns_summaries(
    client: TestClient,
    patch_get_session: Callable[..., MagicMock],
    session_returning_scalars: Callable[[list], MagicMock],
) -> None:
    rows = [_mock_row(entities=[{"food_name": "eggs"}, {"food_name": "toast"}])]
    session = session_returning_scalars(rows)
    patch_get_session(meals_api, session)

    resp = client.get("/meals/log")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["meal_id"] == "meal-1"
    assert body[0]["n_items"] == 2
    assert body[0]["label"] == "Eggs on toast"


def test_list_with_explicit_date_uses_day_bounds_for_date(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_get_session: Callable[..., MagicMock],
    session_returning_scalars: Callable[[list], MagicMock],
) -> None:
    rows = [_mock_row()]
    session = session_returning_scalars(rows)
    patch_get_session(meals_api, session)

    captured = {}
    real_bounds = meals_api.day_bounds_for_date

    def _spy(day):
        captured["day"] = day
        return real_bounds(day)

    monkeypatch.setattr(meals_api, "day_bounds_for_date", _spy)

    resp = client.get("/meals/log", params={"date": "2026-09-10"})

    assert resp.status_code == 200
    assert captured["day"].isoformat() == "2026-09-10"


def test_list_filters_by_meal_type(
    client: TestClient,
    patch_get_session: Callable[..., MagicMock],
    session_returning_scalars: Callable[[list], MagicMock],
) -> None:
    session = session_returning_scalars([_mock_row(meal_type="lunch")])
    patch_get_session(meals_api, session)

    resp = client.get("/meals/log", params={"meal_type": "lunch"})

    assert resp.status_code == 200
    assert resp.json()[0]["meal_type"] == "lunch"


def test_list_invalid_meal_type_422(client: TestClient) -> None:
    resp = client.get("/meals/log", params={"meal_type": "elevenses"})
    assert resp.status_code == 422


def test_list_invalid_date_422(client: TestClient) -> None:
    resp = client.get("/meals/log", params={"date": "not-a-date"})
    assert resp.status_code == 422


def test_list_query_excludes_soft_deleted_and_other_users(
    client: TestClient,
    patch_get_session: Callable[..., MagicMock],
    session_returning_scalars: Callable[[list], MagicMock],
) -> None:
    """The query itself must filter by user_id and deleted_at is NULL.

    Since the DB call is mocked, we assert on the WHERE clause built by
    inspecting the select() passed to session.execute.
    """
    session = session_returning_scalars([])
    patch_get_session(meals_api, session)

    resp = client.get("/meals/log")
    assert resp.status_code == 200
    assert resp.json() == []

    (stmt,), _ = session.execute.call_args
    where_clause = str(stmt.whereclause)
    assert "user_id" in where_clause
    assert "deleted_at" in where_clause


# ---------------------------------------------------------------------------
# GET /meals/log/{meal_id} — detail
# ---------------------------------------------------------------------------


def test_detail_returns_items_verbatim(
    client: TestClient,
    patch_get_session: Callable[..., MagicMock],
    session_returning_scalar_one: Callable[[object], MagicMock],
) -> None:
    items = [{"food_name": "eggs", "qty_g": 100, "fdc_id": 123}]
    row = _mock_row(entities=items)
    session = session_returning_scalar_one(row)
    patch_get_session(meals_api, session)

    resp = client.get("/meals/log/meal-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == items
    assert body["n_items"] == 1


def test_detail_handles_entities_stored_as_json_string(
    client: TestClient,
    patch_get_session: Callable[..., MagicMock],
    session_returning_scalar_one: Callable[[object], MagicMock],
) -> None:
    row = _mock_row(entities='[{"food_name": "rice"}]')
    session = session_returning_scalar_one(row)
    patch_get_session(meals_api, session)

    resp = client.get("/meals/log/meal-1")

    assert resp.status_code == 200
    assert resp.json()["items"] == [{"food_name": "rice"}]


def test_detail_404_when_missing(
    client: TestClient,
    patch_get_session: Callable[..., MagicMock],
    session_returning_scalar_one: Callable[[object], MagicMock],
) -> None:
    session = session_returning_scalar_one(None)
    patch_get_session(meals_api, session)

    resp = client.get("/meals/log/does-not-exist")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Meal not found"


def test_detail_404_for_foreign_owned_or_deleted_is_identical(
    client: TestClient,
    patch_get_session: Callable[..., MagicMock],
    session_returning_scalar_one: Callable[[object], MagicMock],
) -> None:
    """The query filters user_id + deleted_at IS NULL, so a foreign-owned or
    soft-deleted row is indistinguishable from a missing one: the mocked DB
    layer returns None in both cases, and the handler must still 404."""
    session = session_returning_scalar_one(None)
    patch_get_session(meals_api, session)

    resp = client.get("/meals/log/someone-elses-meal")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Meal not found"

    (stmt,), _ = session.execute.call_args
    where_clause = str(stmt.whereclause)
    assert "user_id" in where_clause
    assert "deleted_at" in where_clause
