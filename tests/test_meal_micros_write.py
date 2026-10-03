"""Tests for writing meal_log.micros at log time (spec 008 US1, FR-005,
FR-008, FR-014a, FR-019 "Log again").

The unit tests patch the insert. The DB-backed ones need a real Postgres
(they skip unless DATABASE_URL was set deliberately) and use the bundled USDA
SQLite for server-side resolution.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import text

from backend.agent.tools import meals as meal_tools
from backend.api import meals as meals_api
from backend.db.session import dispose_engine, get_session
from backend.nutrients import resolve
from backend.nutrients.models import MicroValue
from backend.nutrients.resolve import summarise_items
from tests.conftest import DATABASE_URL_PRESET
from tests.factories_micros import make_usda_result

BANANA = 173944
RICE = 168878

needs_db = pytest.mark.skipif(
    not DATABASE_URL_PRESET, reason="needs a real Postgres (set DATABASE_URL)"
)


@pytest.fixture(autouse=True)
async def _fresh_engine():
    """Dispose the cached engine after each test: its asyncpg pool is bound to
    the test's event loop (see backend.db.session.dispose_engine)."""
    yield
    await dispose_engine()


def _patch_side_effects():
    return (
        patch.object(meal_tools, "embed_meal_summary"),
        patch.object(
            meal_tools, "_generate_log_reply", AsyncMock(return_value="Logged!")
        ),
    )


# -- unit: summary computed server-side ---------------------------------------


async def test_log_meal_passes_server_resolved_summary() -> None:
    # The result arrives with bogus client-side micros; they must be ignored.
    item = make_usda_result(micros={"iron": (999.0, "usda")})

    async def fake_resolve(
        fdc_id: int, food_name: str, qty_g: float, rejected: list[str]
    ):
        return resolve.build_item_micros({"iron": (1.0, "usda")}, qty_g)

    embed, reply = _patch_side_effects()
    with (
        embed,
        reply,
        patch.object(meal_tools, "resolve_micros", side_effect=fake_resolve),
        patch.object(
            meal_tools, "_insert_meal_log", AsyncMock(return_value="m1")
        ) as insert,
    ):
        await meal_tools.log_meal("u1", [item], "lunch")

    (micros,) = insert.await_args.kwargs["item_micros"]
    assert micros["iron"] == MicroValue(amount=1.0, source="usda")  # not 999
    assert "fiber" not in micros and "salt" not in micros


async def test_estimate_failure_logs_meal_with_empty_micros() -> None:
    item = make_usda_result(fdc_id=-1, food_name="mystery stew")
    embed, reply = _patch_side_effects()
    with (
        embed,
        reply,
        patch.object(resolve, "_estimate_cache_lookup", AsyncMock(return_value=None)),
        patch.object(
            meal_tools, "_insert_meal_log", AsyncMock(return_value="m1")
        ) as insert,
    ):
        result = await meal_tools.log_meal("u1", [item], "lunch")

    assert result.meal_id == "m1"
    (micros,) = insert.await_args.kwargs["item_micros"]
    assert all(v.source == "unknown" for v in micros.values())


# -- DB-backed ------------------------------------------------------------------


async def _new_user() -> str:
    user_id = str(uuid.uuid4())
    async with get_session()() as session:
        await session.execute(
            text("INSERT INTO user_goal (user_id) VALUES (:u)"), {"u": user_id}
        )
        await session.commit()
    return user_id


async def _stored(meal_id: str) -> tuple[dict, list]:
    """(meal summary computed from the items, stored entities)."""
    async with get_session()() as session:
        row = (
            await session.execute(
                text("SELECT entities FROM meal_log WHERE meal_id = :m"),
                {"m": meal_id},
            )
        ).one()
    return summarise_items(row.entities), row.entities


@needs_db
async def test_log_meal_stores_compact_micros_on_each_item() -> None:
    user_id = await _new_user()
    banana = make_usda_result(food_name="Bananas, raw", fdc_id=BANANA, qty_g=120)
    embed, reply = _patch_side_effects()
    with embed, reply:
        result = await meal_tools.log_meal(user_id, [banana], "snack")

    micros, entities = await _stored(result.meal_id)
    assert entities[0]["micros"]["vitamin_c"] == [pytest.approx(8.7 * 1.2), "u"]
    assert micros["vitamin_c"]["total"] == pytest.approx(8.7 * 1.2)
    assert micros["vitamin_c"]["est"] == 0
    assert micros["vitamin_d"] == {"total": 0.0, "est": 0.0, "known": 1}


@needs_db
async def test_log_items_ignores_client_micros_and_log_again_matches(
    app_factory,
) -> None:
    """Client-sent micros are ignored; re-logging stored items gives the same
    summary at portion 1 (Android "Log again", FR-019)."""
    user_id = await _new_user()
    app = app_factory(meals_api.router, user_id=user_id)
    item = {
        "food_name": "Bananas, raw",
        "qty_g": 120.0,
        "target_qty_g": 120.0,
        "kcal": 107.0,
        "protein_g": 1.3,
        "carbs_g": 27.4,
        "fat_g": 0.4,
        "fiber_g": 3.1,
        "fdc_id": BANANA,
        "source": "USDA",
        "estimated": False,
        "micros": {"vitamin_c": {"amount": 500.0, "source": "usda"}},
        "nutrients": {
            "Vitamin C, total ascorbic acid": {"amount": 500.0, "unit": "mg"}
        },
    }
    embed, reply = _patch_side_effects()
    transport = httpx.ASGITransport(app=app)
    with embed, reply:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            first = await c.post(
                "/meals/log-items", json={"meal_type": "snack", "items": [item]}
            )
            assert first.status_code == 200, first.text
            micros1, entities = await _stored(first.json()["meal_id"])
            assert micros1["vitamin_c"]["total"] == pytest.approx(8.7 * 1.2)

            again = [{**e, "target_qty_g": e["qty_g"]} for e in entities]
            second = await c.post(
                "/meals/log-items", json={"meal_type": "snack", "items": again}
            )
            assert second.status_code == 200, second.text
            micros2, _ = await _stored(second.json()["meal_id"])

    assert micros2 == micros1


@needs_db
async def test_saved_meal_legacy_ingredient_gets_micros() -> None:
    """A saved meal ingredient without micros (pre-008) resolves on log."""
    from types import SimpleNamespace

    from backend.agent.tools.saved_meals import saved_meal_to_results
    from backend.agent.tools.usda import USDAResult

    user_id = await _new_user()
    legacy_meal = SimpleNamespace(
        ingredients=[
            {
                "food_name": "Rice, white, long-grain, regular, enriched, cooked",
                "qty_g": 150.0,
                "kcal": 195.0,
                "protein_g": 4.0,
                "carbs_g": 42.0,
                "fat_g": 0.4,
                "fiber_g": 0.6,
                "fdc_id": RICE,
                "source": "USDA",
                "nutrients": {"Iron, Fe": {"amount": 1.8, "unit": "mg"}},
            }
        ]
    )
    dicts, _ = saved_meal_to_results(legacy_meal)
    results = [USDAResult(**d) for d in dicts]
    embed, reply = _patch_side_effects()
    with embed, reply:
        logged = await meal_tools.log_meal(user_id, results, "lunch")

    micros, _ = await _stored(logged.meal_id)
    assert micros["iron"]["total"] == pytest.approx(1.2 * 1.5)


def test_micro_value_roundtrip() -> None:
    # Guard the model the stored saved-meal ingredients rely on.
    assert MicroValue.model_validate({"amount": None, "source": "unknown"})


# -- saved meals: per-ingredient micros, totals on read (FR-014a) -------------


async def test_saved_meal_stores_ingredient_micros_and_computes_totals() -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from backend.api import my_meals

    async def fake_resolve(fdc_id, food_name, qty_g, rejected=None):
        return resolve.build_item_micros({"iron": (2.0, "usda")}, qty_g)

    raw = [
        {"food_name": "rice", "qty_g": 100.0, "fdc_id": RICE, "nutrients": {"x": 1}},
        {"food_name": "dal", "qty_g": 50.0, "fdc_id": -1, "micros": {"bogus": 1}},
    ]
    with patch.object(my_meals, "resolve_micros", side_effect=fake_resolve):
        stored = await my_meals._with_micros(raw)
        assert all("nutrients" not in i for i in stored)
        assert stored[0]["micros"]["iron"] == [2.0, "u"]  # compact form
        assert "bogus" not in stored[1]["micros"]  # client micros not trusted

        meal = SimpleNamespace(
            id="m",
            name="lunch",
            kcal=1.0,
            protein_g=0.0,
            carbs_g=0.0,
            fat_g=0.0,
            fiber_g=0.0,
            ingredients=stored,
            updated_at=datetime.now(UTC),
        )
        detail = await my_meals._detail(meal)

    assert detail.micros_totals["iron"] == {"total": 3.0, "est": 0.0, "known": 2}
