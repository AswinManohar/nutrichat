"""SC-006: every reader reports the same micronutrient totals (spec 008).

Check-up aggregates, the Mindful daily intake, coaching's micronutrient data
and get_daily_micros must agree for one seeded week. DB-backed.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from backend.agent.tools.history import (
    get_micronutrients_for_range,
    get_nutrient_checkup_aggregates,
)
from backend.agent.tools.mindful import evaluate_safety, get_daily_intake
from backend.db.session import dispose_engine, get_session
from backend.nutrients import catalog
from backend.nutrients.daily import get_daily_micros
from tests.conftest import DATABASE_URL_PRESET

pytestmark = pytest.mark.skipif(
    not DATABASE_URL_PRESET, reason="needs a real Postgres (set DATABASE_URL)"
)

OSLO = ZoneInfo("Europe/Oslo")
END = date(2026, 9, 7)
START = END - timedelta(days=6)


@pytest.fixture(autouse=True)
async def _fresh_engine():
    yield
    await dispose_engine()


async def _seed_week() -> str:
    user_id = str(uuid.uuid4())
    async with get_session()() as session:
        await session.execute(
            text("INSERT INTO user_goal (user_id) VALUES (:u)"), {"u": user_id}
        )
        for d in range(7):
            # two foods per meal, compact per-item micros (data-model §2)
            entities = [
                {
                    "food_name": "a",
                    "micros": {
                        "iron": [1.0 + d, "u"],
                        "total_sugars": [5.0, "u"],
                        "vitamin_b12": [1.5, "u"],
                        "sodium": [1200.0, "u"],
                    },
                },
                {
                    "food_name": "b",
                    "micros": {
                        "iron": [1.0, "e"],
                        "total_sugars": [5.0, "e"],
                        "sodium": [1200.0, "u"],
                    },
                },
            ]
            await session.execute(
                text(
                    "INSERT INTO meal_log (meal_id, user_id, meal_type, kcal, "
                    "protein_g, carbs_g, fat_g, fiber_g, entities, logged_at) "
                    "VALUES (gen_random_uuid(), :u, 'lunch', 500, 20, 60, 15, 6, "
                    "CAST(:ent AS jsonb), :at)"
                ),
                {
                    "u": user_id,
                    "ent": json.dumps(entities),
                    "at": datetime(2026, 9, 1, 12, tzinfo=OSLO) + timedelta(days=d),
                },
            )
        await session.commit()
    return user_id


async def test_all_readers_agree() -> None:
    user_id = await _seed_week()
    keys = ["iron", "total_sugars", "vitamin_b12", "fiber"]
    daily = await get_daily_micros(user_id, START, END, keys=keys)
    week = {
        k: sum(d.values[k].total for d in daily.days if k in d.values) for k in keys
    }

    # Check-up: 7-day daily average × 7 == the week's total.
    checkup = await get_nutrient_checkup_aggregates(user_id, END)
    for key in keys:
        name = catalog.nutrient(key).name
        assert checkup[name]["avg"] * 7 == pytest.approx(week[key])

    # Coaching: micronutrient data for the same range.
    coaching = await get_micronutrients_for_range(
        user_id, START, END, ["iron", "Total Sugars", "Vitamin B-12"]
    )
    assert coaching["iron"]["amount"] == pytest.approx(week["iron"])
    assert coaching["total_sugars"]["amount"] == pytest.approx(week["total_sugars"])
    assert coaching["vitamin_b12"]["amount"] == pytest.approx(week["vitamin_b12"])

    # Mindful: one day's intake equals that day's daily total; sodium ≥ UL alerts.
    first = daily.days[0]
    intake = {n.name: n.amount for n in await get_daily_intake(user_id, START)}
    assert intake["Iron"] == pytest.approx(first.values["iron"].total)
    alerts = evaluate_safety(await get_daily_intake(user_id, START))
    assert any(a.nutrient == "Sodium" and a.limit == 2300 for a in alerts)
