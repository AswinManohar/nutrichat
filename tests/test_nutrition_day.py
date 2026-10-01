"""Regression tests for the single-source-of-truth nutrition day."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.core import nutrition_day as nd
from backend.db import redis_client

_UTC = ZoneInfo("UTC")
_TZ = nd._DAY_TZ
_RESET = nd._DAY_RESET_HOUR


def _local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=_TZ)


_DAY = date(2026, 6, 15)


def test_late_evening_belongs_to_local_date_even_when_utc_rolled_over() -> None:
    # 23:30 local is already the next UTC date for any tz east of UTC-0:30
    # only if offset is negative; assert via explicit conversion either way.
    instant = _local(_DAY, 23, 30).astimezone(_UTC)
    assert nd.nutrition_today(instant) == _DAY


def test_just_before_reset_is_previous_day() -> None:
    instant = _local(_DAY, _RESET) - timedelta(minutes=1)
    assert nd.nutrition_today(instant) == _DAY - timedelta(days=1)


def test_at_and_after_reset_is_current_day() -> None:
    assert nd.nutrition_today(_local(_DAY, _RESET)) == _DAY
    after = _local(_DAY, _RESET) + timedelta(minutes=1)
    assert nd.nutrition_today(after) == _DAY


def test_naive_now_treated_as_utc() -> None:
    aware = _local(_DAY, 12).astimezone(_UTC)
    assert nd.nutrition_today(aware.replace(tzinfo=None)) == _DAY


@pytest.mark.parametrize("offset_days", [0, 1, 30, 200])
def test_day_bounds_round_trip(offset_days: int) -> None:
    day = _DAY + timedelta(days=offset_days)
    start, end = nd.day_bounds(day)
    assert nd.nutrition_today(start) == day
    assert nd.nutrition_today(end - timedelta(microseconds=1)) == day
    assert nd.nutrition_today(end) == day + timedelta(days=1)
    assert start.tzinfo == _UTC and end.tzinfo == _UTC


def test_day_bounds_spans_dst_change_correctly() -> None:
    # Local-midnight arithmetic, not +24h: window ends at the next local reset.
    start, end = nd.day_bounds(date(2026, 3, 29))
    assert end.astimezone(_TZ) == _local(date(2026, 3, 30), _RESET)
    assert start.astimezone(_TZ) == _local(date(2026, 3, 29), _RESET)


def test_redis_client_wrappers_delegate() -> None:
    now = _local(_DAY, 15).astimezone(_UTC)
    assert redis_client.current_day_bounds(now) == nd.current_day_bounds(now)
    assert redis_client.day_bounds_for_date(_DAY) == nd.day_bounds(_DAY)


def test_sql_helper_and_params() -> None:
    assert "AT TIME ZONE" in nd.NUTRITION_DATE_SQL
    assert ":day_tz" in nd.NUTRITION_DATE_SQL
    assert ":day_reset_h" in nd.NUTRITION_DATE_SQL
    assert "logged_at::date" not in nd.NUTRITION_DATE_SQL
    assert nd.nutrition_date_sql("m.logged_at").startswith("((m.logged_at AT")
    assert nd.sql_day_params() == {"day_tz": str(_TZ), "day_reset_h": _RESET}


def test_trends_uses_nutrition_today_and_day_params() -> None:
    from fastapi import FastAPI

    from backend.api.meals import router
    from backend.auth.supabase import get_current_user_id

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"

    result = MagicMock()
    result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session)

    fake_today = date(2026, 6, 15)
    with (
        patch("backend.api.meals.get_session", return_value=factory),
        patch("backend.api.meals.nutrition_today", return_value=fake_today),
    ):
        resp = TestClient(app).get("/meals/trends?days=7")

    assert resp.status_code == 200
    stmt, params = session.execute.await_args.args
    assert nd.NUTRITION_DATE_SQL in str(stmt)
    assert "logged_at::date" not in str(stmt)
    assert params["date_from"] == fake_today - timedelta(days=6)
    assert params["day_tz"] == str(_TZ)
    assert params["day_reset_h"] == _RESET


@pytest.mark.asyncio
async def test_nightly_aggregate_passes_day_params() -> None:
    from backend.workers import tasks

    result = MagicMock()
    result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session)

    with patch("backend.workers.tasks.get_session", return_value=factory):
        await tasks._aggregate_daily_summary(_DAY)

    stmt, params = session.execute.await_args_list[0].args
    assert nd.NUTRITION_DATE_SQL in str(stmt)
    assert params["target_date"] == _DAY
    assert params["day_tz"] == str(_TZ)
    assert params["day_reset_h"] == _RESET
