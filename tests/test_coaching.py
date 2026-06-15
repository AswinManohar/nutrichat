from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.models.test import TestModel

from backend.agent import coaching
from backend.agent.coaching import (
    CoachingAgent,
    QueryParsed,
    _resolve_date_range,
    fetch_data,
    parse_query,
)
from backend.db.models import UserGoal
from backend.db.redis_client import TodayTotals


def _mock_session_factory(goal=None):
    session = MagicMock()
    session.get = AsyncMock(return_value=goal)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def test_resolve_date_range_this_month():
    today = date.today()
    parsed = QueryParsed(time_range="this_month", nutrients=[], include_goals=False)

    date_from, date_to = _resolve_date_range(parsed)

    assert date_from == today.replace(day=1)
    assert date_to == today


def test_resolve_date_range_last_30_days():
    today = date.today()
    parsed = QueryParsed(time_range="last_30_days", nutrients=[], include_goals=False)

    date_from, date_to = _resolve_date_range(parsed)

    assert date_from == today - timedelta(days=29)
    assert date_to == today


def test_resolve_date_range_last_month():
    today = date.today()
    parsed = QueryParsed(time_range="last_month", nutrients=[], include_goals=False)

    date_from, date_to = _resolve_date_range(parsed)

    first_of_this_month = today.replace(day=1)
    last_of_prev_month = first_of_this_month - timedelta(days=1)
    assert date_from == last_of_prev_month.replace(day=1)
    assert date_to == last_of_prev_month
    assert date_from <= date_to < first_of_this_month


def test_resolve_date_range_custom_without_dates_does_not_collapse_to_today():
    today = date.today()
    parsed = QueryParsed(time_range="custom", nutrients=[], include_goals=False)

    date_from, date_to = _resolve_date_range(parsed)

    assert (date_from, date_to) != (today, today)
    assert date_from == today - timedelta(days=29)
    assert date_to == today


def test_resolve_date_range_custom_with_dates_uses_explicit_bounds():
    parsed = QueryParsed(
        time_range="custom",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 15),
        nutrients=[],
        include_goals=False,
    )

    date_from, date_to = _resolve_date_range(parsed)

    assert date_from == date(2026, 1, 1)
    assert date_to == date(2026, 1, 15)


@pytest.mark.asyncio
async def test_parse_query_today_macro():
    test_model = TestModel(
        custom_output_args={
            "time_range": "today",
            "nutrients": ["kcal"],
            "include_goals": False,
        }
    )
    with coaching._parse_agent.override(model=test_model):
        parsed = await parse_query("how many calories today?")

    assert parsed.time_range == "today"
    assert parsed.nutrients == ["kcal"]


@pytest.mark.asyncio
async def test_parse_query_micronutrient():
    test_model = TestModel(
        custom_output_args={
            "time_range": "this_week",
            "nutrients": ["Vitamin B12, total"],
            "include_goals": False,
        }
    )
    with coaching._parse_agent.override(model=test_model):
        parsed = await parse_query("how much B12 this week?")

    assert parsed.time_range == "this_week"
    assert parsed.nutrients == ["Vitamin B12, total"]


@pytest.mark.asyncio
async def test_fetch_data_today_macro_uses_redis():
    parsed = QueryParsed(time_range="today", nutrients=["kcal"], include_goals=True)
    goal = UserGoal(
        user_id="user-1",
        kcal_goal=2000.0,
        protein_goal=150.0,
        fiber_goal=30.0,
        dietary_prefs={},
        streak_days=2,
    )

    with (
        patch(
            "backend.agent.coaching.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(kcal=1240, protein_g=85, fiber_g=10, n_meals=2),
        ) as today_mock,
        patch(
            "backend.agent.coaching.get_session",
            return_value=_mock_session_factory(goal),
        ),
    ):
        data = await fetch_data("user-1", parsed)

    today_mock.assert_awaited_once()
    assert data["today_totals"]["kcal"] == 1240
    assert data["goals"]["kcal_goal"] == 2000.0
    assert data["goals"]["dietary_prefs"] == {}


@pytest.mark.asyncio
async def test_fetch_data_micronutrient_queries_jsonb():
    parsed = QueryParsed(
        time_range="today", nutrients=["Vitamin B12, total"], include_goals=False
    )

    with patch(
        "backend.agent.coaching.get_micronutrients_for_range",
        new_callable=AsyncMock,
        return_value={"Vitamin B12, total": {"amount": 2.1, "unit": "UG"}},
    ) as micro_mock:
        data = await fetch_data("user-1", parsed)

    micro_mock.assert_awaited_once()
    assert data["micronutrients"]["Vitamin B12, total"]["amount"] == 2.1
    # Pure micronutrient query for "today" doesn't need Redis macros.
    assert "today_totals" not in data


@pytest.mark.asyncio
async def test_fetch_data_redis_failure_falls_back_to_postgres():
    parsed = QueryParsed(time_range="today", nutrients=["kcal"], include_goals=False)

    with (
        patch(
            "backend.agent.coaching.get_today_totals",
            new_callable=AsyncMock,
            side_effect=ConnectionError("redis down"),
        ),
        patch(
            "backend.agent.coaching.get_macros_for_range",
            new_callable=AsyncMock,
            return_value={
                "kcal": 1240.0,
                "protein_g": 85.0,
                "carbs_g": 100.0,
                "fat_g": 30.0,
                "fiber_g": 10.0,
                "n_meals": 2,
            },
        ) as macros_mock,
    ):
        data = await fetch_data("user-1", parsed)

    macros_mock.assert_awaited_once()
    assert data["macros"]["kcal"] == 1240.0


@pytest.mark.asyncio
async def test_fetch_data_include_foods_attaches_breakdown():
    parsed = QueryParsed(
        time_range="last_30_days",
        nutrients=[],
        include_goals=False,
        include_foods=True,
    )
    breakdown = {
        "top_foods_by_frequency": [
            {"food_name": "Cheeseburger", "count": 5, "total_kcal": 2750.0}
        ],
        "flagged_junk_foods": [{"food_name": "Cheeseburger", "count": 5}],
        "highest_calorie_foods": [{"food_name": "Cheeseburger", "kcal": 550.0}],
    }

    with (
        patch(
            "backend.agent.coaching.get_macros_for_range",
            new_callable=AsyncMock,
            return_value={
                "kcal": 0.0,
                "protein_g": 0.0,
                "carbs_g": 0.0,
                "fat_g": 0.0,
                "fiber_g": 0.0,
                "n_meals": 0,
            },
        ),
        patch(
            "backend.agent.coaching.get_food_breakdown_for_range",
            new_callable=AsyncMock,
            return_value=breakdown,
        ) as foods_mock,
    ):
        data = await fetch_data("user-1", parsed)

    foods_mock.assert_awaited_once()
    assert data["foods"] == breakdown


@pytest.mark.asyncio
async def test_handle_food_only_question_skips_no_data_exit():
    parsed = QueryParsed(
        time_range="last_30_days",
        nutrients=[],
        include_goals=False,
        include_foods=True,
    )
    breakdown = {
        "top_foods_by_frequency": [
            {"food_name": "Cheeseburger", "count": 5, "total_kcal": 2750.0}
        ],
        "flagged_junk_foods": [{"food_name": "Cheeseburger", "count": 5}],
        "highest_calorie_foods": [{"food_name": "Cheeseburger", "kcal": 550.0}],
    }

    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.get_macros_for_range",
            new_callable=AsyncMock,
            return_value={
                "kcal": 0.0,
                "protein_g": 0.0,
                "carbs_g": 0.0,
                "fat_g": 0.0,
                "fiber_g": 0.0,
                "n_meals": 0,
            },
        ),
        patch(
            "backend.agent.coaching.get_food_breakdown_for_range",
            new_callable=AsyncMock,
            return_value=breakdown,
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="Your most frequent food is the cheeseburger.",
        ) as gen_mock,
    ):
        response = await CoachingAgent().handle(
            "user-1", "what kind of food do I eat the most?"
        )

    gen_mock.assert_awaited_once()
    assert response == "Your most frequent food is the cheeseburger."


@pytest.mark.asyncio
async def test_handle_no_data_delegates_to_generate_response():
    parsed = QueryParsed(time_range="today", nutrients=["kcal"], include_goals=False)

    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="Nothing logged for today yet.",
        ) as gen_mock,
    ):
        response = await CoachingAgent().handle("user-1", "how many calories today?")

    gen_mock.assert_awaited_once()
    assert response == "Nothing logged for today yet."


@pytest.mark.asyncio
async def test_handle_missing_micronutrient_returns_graceful_message():
    parsed = QueryParsed(
        time_range="today", nutrients=["Vitamin B12, total"], include_goals=False
    )

    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.get_micronutrients_for_range",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "backend.agent.coaching.generate_response", new_callable=AsyncMock
        ) as gen_mock,
    ):
        response = await CoachingAgent().handle("user-1", "how much B12 today?")

    assert "Vitamin B12, total" in response
    gen_mock.assert_not_called()


@pytest.mark.asyncio
async def test_handle_with_data_calls_generate_response():
    parsed = QueryParsed(time_range="today", nutrients=["kcal"], include_goals=False)

    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(kcal=1240, protein_g=85, fiber_g=10, n_meals=2),
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="You've had 1,240 kcal today.",
        ) as gen_mock,
    ):
        response = await CoachingAgent().handle("user-1", "how many calories today?")

    gen_mock.assert_awaited_once()
    assert response == "You've had 1,240 kcal today."
