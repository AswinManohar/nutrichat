"""US3 / spec 008: the meal summary leaves the backend with its estimated share
and completeness (meal detail, integration feed, daily totals).

DB-backed; skipped unless DATABASE_URL was set deliberately.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import text

from backend.api import integrations
from backend.api import meals as meals_api
from backend.db.session import dispose_engine, get_session
from backend.nutrients.daily import get_daily_micros, range_totals
from tests.conftest import DATABASE_URL_PRESET

pytestmark = pytest.mark.skipif(
    not DATABASE_URL_PRESET, reason="needs a real Postgres (set DATABASE_URL)"
)

OSLO = ZoneInfo("Europe/Oslo")


@pytest.fixture(autouse=True)
async def _fresh_engine():
    yield
    await dispose_engine()


async def _seed(user_id: str, at: datetime, micros: dict, deleted: bool = False) -> str:
    meal_id = str(uuid.uuid4())
    async with get_session()() as session:
        await session.execute(
            text(
                "INSERT INTO meal_log (meal_id, user_id, meal_type, kcal, "
                "protein_g, carbs_g, fat_g, fiber_g, entities, micros, logged_at, "
                "deleted_at) VALUES (:m, :u, 'lunch', 300, 10, 40, 8, 4, "
                '\'[{"food_name": "dal", "qty_g": 150}]\'::jsonb, '
                "CAST(:mic AS jsonb), :at, :del)"
            ),
            {
                "m": meal_id,
                "u": user_id,
                "mic": json.dumps(micros),
                "at": at,
                "del": at if deleted else None,
            },
        )
        await session.commit()
    return meal_id


async def _user() -> str:
    user_id = str(uuid.uuid4())
    async with get_session()() as session:
        await session.execute(
            text("INSERT INTO user_goal (user_id) VALUES (:u)"), {"u": user_id}
        )
        await session.commit()
    return user_id


async def test_meal_detail_includes_micros_and_items_have_no_nutrients(
    app_factory,
) -> None:
    user_id = await _user()
    meal_id = await _seed(
        user_id,
        datetime(2026, 9, 1, 12, tzinfo=OSLO),
        {"iron": {"total": 3.0, "est": 1.5, "known": 1}},
    )
    app = app_factory(meals_api.router, user_id=user_id)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get(f"/meals/log/{meal_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["micros"]["iron"] == {"total": 3.0, "est": 1.5, "known": 1}
    assert all("nutrients" not in item for item in body["items"])


async def test_integration_feed_carries_micros_not_on_tombstones(app_factory) -> None:
    user_id = await _user()
    at = datetime(2026, 9, 1, 12, tzinfo=OSLO)
    live = await _seed(
        user_id, at, {"sodium": {"total": 900.0, "est": 0.0, "known": 1}}
    )
    gone = await _seed(
        user_id, at, {"sodium": {"total": 1.0, "est": 0.0, "known": 1}}, True
    )

    async def _auth() -> str:
        return user_id

    app = app_factory(integrations.router, user_id=None)
    app.dependency_overrides[integrations.get_integration_user] = _auth
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/v1/integrations/meals")
    assert resp.status_code == 200, resp.text
    by_id = {m["meal_id"]: m for m in resp.json()["items"]}
    assert by_id[live]["micros"]["sodium"]["total"] == 900.0
    assert by_id[gone]["deleted"] is True
    assert by_id[gone].get("micros") is None


async def test_half_estimated_week_reports_half_estimated_iron() -> None:
    user_id = await _user()
    start = date(2026, 9, 1)
    for d in range(7):
        await _seed(
            user_id,
            datetime(2026, 9, 1, 12, tzinfo=OSLO) + timedelta(days=d),
            {"iron": {"total": 4.0, "est": 2.0, "known": 2}},
        )
    week = range_totals(
        await get_daily_micros(user_id, start, start + timedelta(days=6), ["iron"])
    )
    assert week["iron"].est / week["iron"].total == pytest.approx(0.5, abs=0.01)
