from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models.test import TestModel

from backend.agent import coaching
from backend.agent.coaching import (
    CoachingAgent,
    QueryParsed,
    _resolve_date_range,
    fetch_data,
    generate_response,
    parse_query,
)
from backend.agent.context import ContextBundle, GoalSummary
from backend.db.models import UserGoal
from backend.db.redis_client import CoachingTurn, TodayTotals


@pytest.fixture(autouse=True)
def _no_user_state():
    """Keep build_context (Postgres + embeddings) and the Redis history off
    the real backends for every test; tests that care override these."""
    with (
        patch(
            "backend.agent.coaching.build_context",
            new_callable=AsyncMock,
            return_value=ContextBundle(today_totals=TodayTotals()),
        ),
        patch(
            "backend.agent.coaching.get_coaching_history",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        yield


_HISTORY = [
    CoachingTurn(role="user", content="how much protein today?"),
    CoachingTurn(role="assistant", content="95g so far."),
]


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


@pytest.mark.asyncio
async def test_handle_meal_plan_feeds_today_totals_and_goals():
    """A "what can I eat to hit my goals" query must ground generate_response
    in BOTH today's totals and the daily goals (incl. dietary_prefs) so the
    model can compute REMAINING = goal - today and propose a recipe-card plan.

    Meal-suggestion queries are parsed to time_range="today" +
    include_goals=True (see query_parse_system.md); this test pins the
    contract that fetch_data then hands both blocks to the response model.
    """
    parsed = QueryParsed(time_range="today", nutrients=[], include_goals=True)
    goal = UserGoal(
        user_id="user-1",
        kcal_goal=2000.0,
        protein_goal=120.0,
        fiber_goal=30.0,
        dietary_prefs={"vegan": True},
        streak_days=0,
    )

    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(kcal=1450, protein_g=78, fiber_g=14, n_meals=2),
        ),
        patch(
            "backend.agent.coaching.get_session",
            return_value=_mock_session_factory(goal),
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="**🥗 Your plan to hit today's goals**\n...",
        ) as gen_mock,
    ):
        await CoachingAgent().handle("user-1", "what can I eat today to hit my goals?")

    gen_mock.assert_awaited_once()
    _, data = gen_mock.await_args.args
    # Both blocks present so REMAINING can be computed per macro.
    assert data["today_totals"]["protein_g"] == 78
    assert data["goals"]["protein_goal"] == 120.0
    # Dietary prefs must reach the model so suggestions can respect them.
    assert data["goals"]["dietary_prefs"] == {"vegan": True}


# ---------------------------------------------------------------------------
# User context + conversation history wiring
# ---------------------------------------------------------------------------


async def test_generate_response_puts_user_context_in_instructions():
    ctx = ContextBundle(
        today_totals=TodayTotals(kcal=1450, protein_g=95, fiber_g=18, n_meals=3),
        goals=GoalSummary(
            kcal_goal=2200,
            protein_goal=140,
            fiber_goal=30,
            dietary_prefs={},
            streak_days=4,
        ),
        preferences=["dislikes mushrooms"],
    )
    context_prompt = coaching.build_system_prompt(ctx)

    with (
        coaching._response_agent.override(model=TestModel()),
        capture_run_messages() as msgs,
    ):
        await generate_response(
            "am I on track?", {"today_totals": {}}, context_prompt=context_prompt
        )

    first = msgs[0]
    assert isinstance(first, ModelRequest)
    assert "dislikes mushrooms" in first.instructions
    assert "Current streak: 4 day(s)" in first.instructions
    # The static rule set is still there alongside the per-user block.
    assert "Ground every answer strictly in the provided data" in first.instructions


async def test_generate_response_replays_history_before_the_question():
    with (
        coaching._response_agent.override(model=TestModel()),
        capture_run_messages() as msgs,
    ):
        await generate_response("and yesterday?", {"macros": {}}, history=_HISTORY)

    # history (request, response) then the new request
    assert [type(m) for m in msgs[:3]] == [ModelRequest, ModelResponse, ModelRequest]
    assert msgs[0].parts[0].content == "how much protein today?"
    assert msgs[1].parts[0].content == "95g so far."
    assert "and yesterday?" in msgs[2].parts[-1].content


async def test_generate_response_without_history_starts_with_the_question():
    with (
        coaching._response_agent.override(model=TestModel()),
        capture_run_messages() as msgs,
    ):
        await generate_response("how am I doing?", {"macros": {}})

    assert isinstance(msgs[0], ModelRequest)
    assert "how am I doing?" in msgs[0].parts[-1].content


async def test_parse_query_sees_recent_conversation():
    test_model = TestModel(
        custom_output_args={"time_range": "yesterday", "nutrients": ["protein_g"]}
    )
    with (
        coaching._parse_agent.override(model=test_model),
        capture_run_messages() as msgs,
    ):
        await parse_query("and yesterday?", history=_HISTORY)

    prompt = msgs[0].parts[-1].content
    assert "how much protein today?" in prompt
    assert "95g so far." in prompt
    assert prompt.rstrip().endswith("and yesterday?")


async def test_parse_query_without_history_has_no_conversation_block():
    test_model = TestModel(custom_output_args={"time_range": "today", "nutrients": []})
    with (
        coaching._parse_agent.override(model=test_model),
        capture_run_messages() as msgs,
    ):
        await parse_query("how many calories today?")

    prompt = msgs[0].parts[-1].content
    assert "Recent conversation" not in prompt


async def test_handle_threads_context_and_history_into_both_llm_calls():
    parsed = QueryParsed(time_range="yesterday", nutrients=["protein_g"])
    ctx = ContextBundle(
        today_totals=TodayTotals(kcal=1450, protein_g=95, fiber_g=18, n_meals=3),
        preferences=["vegetarian"],
    )

    with (
        patch(
            "backend.agent.coaching.get_coaching_history",
            new_callable=AsyncMock,
            return_value=_HISTORY,
        ),
        patch(
            "backend.agent.coaching.build_context",
            new_callable=AsyncMock,
            return_value=ctx,
        ) as ctx_mock,
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ) as parse_mock,
        patch(
            "backend.agent.coaching.get_macros_for_range",
            new_callable=AsyncMock,
            return_value={"protein_g": 120, "n_meals": 3},
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="120g yesterday.",
        ) as gen_mock,
    ):
        reply = await CoachingAgent().handle("user-1", "and yesterday?")

    assert reply == "120g yesterday."
    ctx_mock.assert_awaited_once_with("user-1", "and yesterday?")
    assert parse_mock.await_args.kwargs["history"] == _HISTORY
    kwargs = gen_mock.await_args.kwargs
    assert kwargs["history"] == _HISTORY
    assert "vegetarian" in kwargs["context_prompt"]


async def test_handle_answers_without_context_when_build_context_fails():
    parsed = QueryParsed(time_range="today", nutrients=["kcal"])

    with (
        patch(
            "backend.agent.coaching.build_context",
            new_callable=AsyncMock,
            side_effect=RuntimeError("embedding API down"),
        ),
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
            return_value="1,240 kcal today.",
        ) as gen_mock,
    ):
        reply = await CoachingAgent().handle("user-1", "how many calories today?")

    assert reply == "1,240 kcal today."
    assert gen_mock.await_args.kwargs["context_prompt"] == ""
