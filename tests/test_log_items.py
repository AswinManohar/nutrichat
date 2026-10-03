"""Tests for POST /meals/log-items — direct (no-LLM) confirmation-card logging."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from backend.agent.tools.meals import MealLogResult
from backend.api import meals


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


def _app_with_auth(app_factory) -> tuple[FastAPI, AsyncMock]:
    app = app_factory(meals.router)
    return app, AsyncMock(return_value=_result())


def test_requires_auth(app_factory) -> None:
    client = TestClient(app_factory(meals.router, user_id=None))
    resp = client.post(
        "/meals/log-items",
        json={"meal_type": "lunch", "items": [_item("rice", 150, 150, 200)]},
    )
    assert resp.status_code == 401


def test_logs_with_gram_and_portion_scaling(app_factory) -> None:
    app, logged = _app_with_auth(app_factory)
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
    # Micros are re-derived server-side in log_meal (spec 008), not scaled
    # from client data.
    assert not hasattr(results[0], "nutrients")
    assert logged.call_args.args[2] == "dinner"


def test_label_prefers_source_dish(app_factory) -> None:
    app, logged = _app_with_auth(app_factory)
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


def test_only_sent_items_logged(app_factory) -> None:
    # The frontend drops removed items; the endpoint logs exactly what it gets.
    app, logged = _app_with_auth(app_factory)
    client = TestClient(app)
    with patch("backend.api.meals.persist_meal", logged):
        resp = client.post(
            "/meals/log-items",
            json={"meal_type": "lunch", "items": [_item("chicken", 60, 60, 100)]},
        )
    assert resp.status_code == 200
    results = logged.call_args.args[1]
    assert [r.food_name for r in results] == ["chicken"]


def test_bad_meal_type_422(app_factory) -> None:
    app, logged = _app_with_auth(app_factory)
    client = TestClient(app)
    with patch("backend.api.meals.persist_meal", logged):
        resp = client.post(
            "/meals/log-items",
            json={"meal_type": "brinner", "items": [_item("rice", 150, 150, 200)]},
        )
    assert resp.status_code == 422
    logged.assert_not_called()


def test_empty_items_422(app_factory) -> None:
    app, _ = _app_with_auth(app_factory)
    client = TestClient(app)
    resp = client.post("/meals/log-items", json={"meal_type": "lunch", "items": []})
    assert resp.status_code == 422


def test_zero_target_qty_422(app_factory) -> None:
    app, _ = _app_with_auth(app_factory)
    client = TestClient(app)
    resp = client.post(
        "/meals/log-items",
        json={"meal_type": "lunch", "items": [_item("rice", 150, 0, 200)]},
    )
    assert resp.status_code == 422


# NOTE ON FIXTURE PATTERN: this test file has no `client`/`db_session`
# fixtures — every existing test above builds its own TestClient inline and
# stubs `backend.api.meals.persist_meal` (no real Postgres in these tests).
# The dedup tests below follow that same pattern and additionally stub the
# new `backend.api.meals._find_by_client_request_id` DB lookup, since the
# dedup path reads from Postgres before/around the persist_meal call.

_CLIENT_REQUEST_ID = "11111111-1111-1111-1111-111111111111"


def _existing_row() -> SimpleNamespace:
    """A stand-in for the MealLog ORM row _dedup_result() reads from."""
    return SimpleNamespace(
        meal_id="m1",
        meal_type="lunch",
        entities=[{"food_name": "banana, raw"}],
        kcal=105.0,
        protein_g=1.3,
        carbs_g=27.0,
        fat_g=0.4,
        fiber_g=3.1,
    )


def test_log_items_dedupes_on_client_request_id(app_factory) -> None:
    app, logged = _app_with_auth(app_factory)
    client = TestClient(app)
    body = {
        "meal_type": "lunch",
        "portion": 1.0,
        "client_request_id": _CLIENT_REQUEST_ID,
        "items": [_item("banana, raw", 118, 118, 105)],
    }

    # First call: no existing row yet -> persists normally.
    with (
        patch("backend.api.meals.persist_meal", logged),
        patch(
            "backend.api.meals._find_by_client_request_id",
            AsyncMock(return_value=None),
        ),
    ):
        first = client.post("/meals/log-items", json=body)
    assert first.status_code == 200
    assert first.json()["deduplicated"] is False
    assert first.json()["meal_id"] == "m1"
    logged.assert_called_once()

    # Second call (replay): pre-select finds the row from the first call.
    with (
        patch("backend.api.meals.persist_meal", logged),
        patch(
            "backend.api.meals._find_by_client_request_id",
            AsyncMock(return_value=_existing_row()),
        ),
    ):
        second = client.post("/meals/log-items", json=body)
    assert second.status_code == 200
    assert second.json()["deduplicated"] is True
    assert second.json()["meal_id"] == first.json()["meal_id"]
    # The pre-select short-circuited — persist_meal was not called again.
    logged.assert_called_once()


def test_log_items_race_duplicate_falls_back_to_existing_row(app_factory) -> None:
    """Exercises the race-path IntegrityError branch in log_items.

    Simulates two concurrent replays both passing the pre-select (both see
    no existing row), then both attempting to insert: the second loses the
    unique-index race and must fall back to re-selecting the winner instead
    of surfacing a 500.
    """
    app, _ = _app_with_auth(app_factory)
    client = TestClient(app)
    body = {
        "meal_type": "lunch",
        "portion": 1.0,
        "client_request_id": _CLIENT_REQUEST_ID,
        "items": [_item("banana, raw", 118, 118, 105)],
    }

    persist_mock = AsyncMock(
        side_effect=IntegrityError(
            "insert into meal_log ...", {}, Exception("duplicate key value")
        )
    )
    # Pre-select misses (fast-path lost the race); re-select after the
    # IntegrityError finds the winner row from the other request.
    find_mock = AsyncMock(side_effect=[None, _existing_row()])

    with (
        patch("backend.api.meals.persist_meal", persist_mock),
        patch("backend.api.meals._find_by_client_request_id", find_mock),
    ):
        resp = client.post("/meals/log-items", json=body)

    assert resp.status_code == 200
    assert resp.json()["deduplicated"] is True
    assert resp.json()["meal_id"] == "m1"
    persist_mock.assert_called_once()
    assert find_mock.call_count == 2


def test_log_items_without_client_request_id_still_logs(app_factory) -> None:
    """No idempotency key -> behaves exactly like before (no dedup lookup)."""
    app, logged = _app_with_auth(app_factory)
    client = TestClient(app)
    with (
        patch("backend.api.meals.persist_meal", logged),
        patch(
            "backend.api.meals._find_by_client_request_id",
            AsyncMock(side_effect=AssertionError("should not be called")),
        ),
    ):
        resp = client.post(
            "/meals/log-items",
            json={"meal_type": "lunch", "items": [_item("chicken", 60, 60, 100)]},
        )
    assert resp.status_code == 200
    assert resp.json()["deduplicated"] is False


def _saved_meal_session(make_session, meal: SimpleNamespace | None):
    session = make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = meal
    session.execute = AsyncMock(return_value=result)
    return session


def test_saved_meal_id_stamps_flag_and_label(app_factory, make_session) -> None:
    app, logged = _app_with_auth(app_factory)
    session = _saved_meal_session(
        make_session, SimpleNamespace(id="sm1", name="Chicken biryani")
    )
    with (
        patch("backend.api.meals.persist_meal", logged),
        patch(
            "backend.api.meals.get_session",
            return_value=MagicMock(return_value=session),
        ),
    ):
        resp = TestClient(app).post(
            "/meals/log-items",
            json={
                "meal_type": "lunch",
                "saved_meal_id": "sm1",
                "items": [_item("rice", 150, 150, 200)],
            },
        )
    assert resp.status_code == 200
    assert logged.call_args.kwargs["label"] == "Chicken biryani"
    assert logged.call_args.kwargs["extra_flags"] == {"saved_meal_id": "sm1"}


def test_foreign_or_unknown_saved_meal_id_ignored(app_factory, make_session) -> None:
    app, logged = _app_with_auth(app_factory)
    session = _saved_meal_session(make_session, None)
    with (
        patch("backend.api.meals.persist_meal", logged),
        patch(
            "backend.api.meals.get_session",
            return_value=MagicMock(return_value=session),
        ),
    ):
        resp = TestClient(app).post(
            "/meals/log-items",
            json={
                "meal_type": "lunch",
                "saved_meal_id": "someone-elses",
                "items": [_item("rice", 150, 150, 200)],
            },
        )
    assert resp.status_code == 200
    assert logged.call_args.kwargs["label"] == "rice"
    assert logged.call_args.kwargs["extra_flags"] is None
