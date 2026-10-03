"""Tests for per-day micronutrient totals (spec 008 FR-017, SC-005, SC-008).

Covers contracts/daily-totals.md: no-data days, derived salt, fiber from its
column, soft deletes, the nutrition-day boundary, validation and speed.
DB-backed; skipped unless DATABASE_URL was set deliberately.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import text

from backend.api import nutrients as nutrients_api
from backend.db.session import dispose_engine, get_session
from backend.nutrients import catalog
from backend.nutrients.daily import get_daily_micros
from tests.conftest import DATABASE_URL_PRESET

pytestmark = pytest.mark.skipif(
    not DATABASE_URL_PRESET, reason="needs a real Postgres (set DATABASE_URL)"
)

OSLO = ZoneInfo("Europe/Oslo")  # tunables day.timezone; reset_hour 1
D1 = date(2026, 9, 1)


@pytest.fixture(autouse=True)
async def _fresh_engine():
    yield
    await dispose_engine()


async def _user() -> str:
    user_id = str(uuid.uuid4())
    async with get_session()() as session:
        await session.execute(
            text("INSERT INTO user_goal (user_id) VALUES (:u)"), {"u": user_id}
        )
        await session.commit()
    return user_id


Food = dict[str, tuple[float, str]]  # key -> (amount, "u" | "e")


async def _meal(
    user_id: str,
    at: datetime,
    foods: list[Food],
    *,
    fiber_g: float = 0.0,
    deleted: bool = False,
    label: str = "meal",
) -> str:
    """Insert a meal whose items carry compact micros (spec 008 §2)."""
    meal_id = str(uuid.uuid4())
    entities = [
        {"food_name": f"f{i}", "micros": {k: [a, s] for k, (a, s) in food.items()}}
        for i, food in enumerate(foods)
    ]
    async with get_session()() as session:
        await session.execute(
            text(
                "INSERT INTO meal_log (meal_id, user_id, meal_type, kcal, "
                "protein_g, carbs_g, fat_g, fiber_g, entities, label, "
                "logged_at, deleted_at) VALUES (:m, :u, 'lunch', 100, 1, 1, 1, "
                ":fib, CAST(:ent AS jsonb), :label, :at, :del)"
            ),
            {
                "m": meal_id,
                "u": user_id,
                "fib": fiber_g,
                "ent": json.dumps(entities),
                "label": label,
                "at": at,
                "del": at if deleted else None,
            },
        )
        await session.commit()
    return meal_id


def _noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=OSLO)


async def test_every_day_returned_and_empty_days_are_no_data() -> None:
    u = await _user()
    await _meal(u, _noon(D1), [{"iron": (2.0, "u")}, {"iron": (1.0, "e")}])
    resp = await get_daily_micros(u, D1, D1 + timedelta(days=2), keys=["iron"])
    assert [d.date for d in resp.days] == [D1 + timedelta(days=i) for i in range(3)]
    assert resp.days[0].logged and resp.days[0].values["iron"].total == 3.0
    assert not resp.days[1].logged and resp.days[1].values == {}


async def test_salt_derived_from_sodium_and_fiber_from_column() -> None:
    u = await _user()
    foods = [{"sodium": (1600.0, "u")}, {"sodium": (400.0, "e")}]
    await _meal(u, _noon(D1), foods, fiber_g=7.5)
    day = (await get_daily_micros(u, D1, D1, keys=["salt", "fiber"])).days[0]
    assert day.values["salt"].total == pytest.approx(5.0)
    assert day.values["salt"].est == pytest.approx(1.0)
    assert day.values["fiber"].total == pytest.approx(7.5)
    assert day.values["fiber"].est == 0
    assert day.values["fiber"].known == day.items == 2


async def test_sums_across_meals_and_skips_deleted() -> None:
    u = await _user()
    await _meal(u, _noon(D1), [{"iron": (1.0, "u")}])
    await _meal(u, _noon(D1), [{"iron": (2.0, "e")}])
    await _meal(u, _noon(D1), [{"iron": (50.0, "u")}], deleted=True)
    day = (await get_daily_micros(u, D1, D1, keys=["iron"])).days[0]
    assert day.n_meals == 2
    assert day.values["iron"].total == pytest.approx(3.0)
    assert day.values["iron"].est == pytest.approx(2.0)
    assert day.values["iron"].known == 2


async def test_nutrition_day_boundary() -> None:
    u = await _user()
    # 00:30 local on D2 is before the 01:00 reset -> belongs to D1.
    late = datetime(2026, 9, 2, 0, 30, tzinfo=OSLO)
    await _meal(u, late, [{"iron": (4.0, "u")}])
    resp = await get_daily_micros(u, D1, D1 + timedelta(days=1), keys=["iron"])
    assert resp.days[0].values["iron"].total == 4.0
    assert resp.days[1].logged is False


async def test_unknown_key_absent_and_meal_contributions() -> None:
    u = await _user()
    meal_id = await _meal(
        u, _noon(D1), [{"iron": (1.0, "u")}, {"zinc": (0.5, "e")}], label="dal"
    )
    resp = await get_daily_micros(
        u, D1, D1, keys=["iron", "biotin"], include_meals=True
    )
    day = resp.days[0]
    assert "biotin" not in day.values  # unknown everywhere
    assert day.meals[0].meal_id == meal_id and day.meals[0].label == "dal"
    assert day.meals[0].values["iron"].total == 1.0
    # spec 004 top contributors: per-food values
    assert [f.food_name for f in day.meals[0].foods] == ["f0", "f1"]
    assert day.meals[0].foods[0].values["iron"].total == 1.0
    assert "iron" not in day.meals[0].foods[1].values


async def test_rejects_bad_requests() -> None:
    with pytest.raises(ValueError):
        await get_daily_micros("u", D1, D1 + timedelta(days=365))
    with pytest.raises(ValueError):
        await get_daily_micros("u", D1, D1, keys=["unobtainium"])
    with pytest.raises(ValueError):
        await get_daily_micros("u", D1, D1 - timedelta(days=1))


async def test_endpoint_contract(app_factory) -> None:
    u = await _user()
    await _meal(u, _noon(D1), [{"sodium": (1000.0, "u")}])
    app = app_factory(nutrients_api.router, user_id=u)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        ok = await c.get(
            "/nutrients/daily",
            params={"from": "2026-09-01", "to": "2026-09-02", "keys": "sodium,salt"},
        )
        too_long = await c.get(
            "/nutrients/daily", params={"from": "2025-12-31", "to": "2026-12-31"}
        )
        bad_key = await c.get(
            "/nutrients/daily",
            params={"from": "2026-09-01", "to": "2026-09-01", "keys": "nope"},
        )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["from"] == "2026-09-01"
    assert body["days"][0]["values"]["salt"]["total"] == pytest.approx(2.5)
    assert body["days"][1] == {
        "date": "2026-09-02",
        "logged": False,
        "n_meals": 0,
        "items": 0,
        "values": {},
    }
    assert too_long.status_code == 422
    assert bad_key.status_code == 422


async def test_90_days_all_keys_under_one_second() -> None:
    """SC-008: 90 days × 4 meals × 3 foods, every key known."""
    u = await _user()
    item = {
        "food_name": "x",
        "micros": {k: [0.5, "u"] for k in catalog.stored_keys()},
    }
    entities = json.dumps([item, item, item])
    async with get_session()() as session:
        for d in range(90):
            for h in (8, 12, 16, 20):
                at = datetime(2026, 6, 1, h, tzinfo=OSLO) + timedelta(days=d)
                await session.execute(
                    text(
                        "INSERT INTO meal_log (meal_id, user_id, meal_type, kcal, "
                        "protein_g, carbs_g, fat_g, fiber_g, entities, logged_at) "
                        "VALUES (gen_random_uuid(), :u, 'lunch', 1, 1, 1, 1, 1, "
                        "CAST(:ent AS jsonb), :at)"
                    ),
                    {"u": u, "ent": entities, "at": at},
                )
        await session.commit()
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        await get_daily_micros(u, date(2026, 6, 1), date(2026, 8, 29))
        timings.append(time.perf_counter() - start)
    assert max(timings) < 1.0
