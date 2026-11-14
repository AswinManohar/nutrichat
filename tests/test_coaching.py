from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from backend.agent import coaching
from backend.agent.coaching import (
    CoachingAgent,
    QueryParsed,
    RestrictionsUnavailableError,
    _resolve_date_range,
    fetch_data,
    generate_response,
    parse_query,
)
from backend.agent.context import ContextBundle, GoalSummary
from backend.agent.food.usda_local import FoodDbUnavailable
from backend.agent.memory import MemoryFact
from backend.agent.memory_curator import TurnExtraction
from backend.agent.memory_tools import hard_writes
from backend.agent.suggest import SuggestionResult
from backend.config import get_tunables
from backend.db.models import UserGoal
from backend.db.redis_client import CoachingTurn, TodayTotals
from backend.safety import profile
from tests.profile_helpers import hard_entry
from tests.recipe_helpers import make_recipe


@pytest.fixture(autouse=True)
def hard_entries():
    """Keep build_context (Postgres + embeddings), the Redis history and the
    hard profile off the real backends for every test; tests that care
    override these. Yields the live hard entries the tests may fill."""
    entries: list = []
    with (
        patch(
            "backend.agent.coaching.load_hard_profile",
            new_callable=AsyncMock,
            return_value=entries,
        ),
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
        yield entries


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


async def test_fetch_data_today_macro_uses_redis(hard_entries):
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
    assert response.message == "Your most frequent food is the cheeseburger."


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
    assert response.message == "Nothing logged for today yet."


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

    assert "Vitamin B12, total" in response.message
    gen_mock.assert_not_called()


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
    assert response.message == "You've had 1,240 kcal today."


async def test_handle_meal_plan_feeds_today_totals_and_goals(hard_entries):
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
        streak_days=0,
    )
    hard_entries.append(hard_entry(profile.DietSettingValue(setting="vegan")))

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


def _fact(text: str, kind: str) -> MemoryFact:
    return MemoryFact(id=text, fact=text, kind=kind, source="stated")


async def test_generate_response_puts_user_context_in_instructions():
    ctx = ContextBundle(
        today_totals=TodayTotals(kcal=1450, protein_g=95, fiber_g=18, n_meals=3),
        goals=GoalSummary(
            kcal_goal=2200,
            protein_goal=140,
            fiber_goal=30,
            streak_days=4,
        ),
        profile=[_fact("dislikes mushrooms", "dislike")],
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
        profile=[_fact("vegetarian", "habit")],
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

    assert reply.message == "120g yesterday."
    ctx_mock.assert_awaited_once_with("user-1", [])
    assert parse_mock.await_args.kwargs["history"] == _HISTORY
    kwargs = gen_mock.await_args.kwargs
    assert kwargs["history"] == _HISTORY
    assert "vegetarian" in kwargs["context_prompt"]


async def test_handle_keeps_restrictions_when_build_context_fails():
    parsed = QueryParsed(time_range="today", nutrients=["kcal"])
    restrictions = ContextBundle(
        today_totals=TodayTotals(),
        goals=GoalSummary(streak_days=0),
        hard_block=(
            "Patient safety profile (confirmed by the patient):\n"
            "- Diet settings (binding): vegetarian\n"
            "- Declared health conditions: diabetes."
        ),
    )

    with (
        patch(
            "backend.agent.coaching.build_context",
            new_callable=AsyncMock,
            side_effect=RuntimeError("embedding API down"),
        ),
        patch(
            "backend.agent.coaching.load_restrictions",
            new_callable=AsyncMock,
            return_value=restrictions,
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

    assert reply.message == "1,240 kcal today."
    prompt = gen_mock.await_args.kwargs["context_prompt"]
    assert "Diet settings (binding): vegetarian" in prompt
    assert "Declared health conditions: diabetes." in prompt
    # The fallback carries no totals, so it cannot state stale numbers.
    assert "Today so far" not in prompt


async def test_handle_fails_when_restrictions_cannot_be_loaded():
    with (
        patch(
            "backend.agent.coaching.build_context",
            new_callable=AsyncMock,
            side_effect=RuntimeError("embedding API down"),
        ),
        patch(
            "backend.agent.coaching.load_restrictions",
            new_callable=AsyncMock,
            side_effect=OSError("postgres down"),
        ),
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=QueryParsed(time_range="today", nutrients=["kcal"]),
        ),
        patch(
            "backend.agent.coaching.generate_response", new_callable=AsyncMock
        ) as gen_mock,
        pytest.raises(RestrictionsUnavailableError),
    ):
        await CoachingAgent().handle("user-1", "what should I eat for dinner?")

    gen_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Spec 013 US2: meal requests, one profile load, reply guard
# ---------------------------------------------------------------------------


async def test_handle_answers_a_meal_request_with_a_checked_recipe(hard_entries):
    parsed = QueryParsed(time_range="today", suggests_meal=True)
    recipe = make_recipe("rice")
    suggestion = SuggestionResult(
        message="Rice bowl ...",
        recipe=recipe,
        recommendation_id="rec-1",
        constraint_note="Kept this free of peanut.",
        attempts=1,
    )
    entry = hard_entry(profile.AllergyValue(allergen_group="peanut"))
    hard_entries.append(entry)

    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.suggest_meal",
            new_callable=AsyncMock,
            return_value=suggestion,
        ) as suggest_mock,
        patch(
            "backend.agent.coaching.generate_response", new_callable=AsyncMock
        ) as gen_mock,
    ):
        result = await CoachingAgent().handle("user-1", "what should I eat tonight?")

    assert result.message == "Rice bowl ..."
    assert (result.recipe, result.recommendation_id) == (recipe, "rec-1")
    assert result.constraint_note == "Kept this free of peanut."
    assert suggest_mock.await_args.args[3] == [entry]
    gen_mock.assert_not_awaited()


async def test_handle_loads_the_hard_profile_once_per_turn(hard_entries):
    parsed = QueryParsed(
        time_range="today", nutrients=["kcal"], include_goals=True, needs_guidance=True
    )
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
            "backend.agent.coaching.load_hard_profile",
            new_callable=AsyncMock,
            return_value=hard_entries,
        ) as load_mock,
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(kcal=1240),
        ),
        patch(
            "backend.agent.coaching.get_session",
            return_value=_mock_session_factory(goal),
        ),
        patch(
            "backend.agent.coaching.retrieve", new_callable=AsyncMock, return_value=[]
        ) as retrieve_mock,
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="ok",
        ),
    ):
        await CoachingAgent().handle("user-1", "how am I doing on calories?")

    load_mock.assert_awaited_once()
    retrieve_mock.assert_awaited_once()


async def test_handle_stops_when_the_profile_cannot_be_loaded():
    with (
        patch(
            "backend.agent.coaching.load_hard_profile",
            new_callable=AsyncMock,
            side_effect=OSError("postgres down"),
        ),
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=QueryParsed(time_range="today", suggests_meal=True),
        ),
        patch("backend.agent.coaching.suggest_meal", new_callable=AsyncMock) as mock,
        pytest.raises(RestrictionsUnavailableError),
    ):
        await CoachingAgent().handle("user-1", "dinner idea?")

    mock.assert_not_awaited()


def _scripted_replies(*replies: str):
    """A model that answers with each reply in turn, then repeats the last."""
    seen: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        text = replies[min(len(seen), len(replies)) - 1]
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(respond), seen


def _peanut_allergy() -> list:
    return [hard_entry(profile.AllergyValue(allergen_group="peanut"))]


async def test_the_reply_guard_sends_a_violating_reply_back_for_a_rewrite():
    model, seen = _scripted_replies(
        "Try a peanut butter sandwich.", "Try a turkey sandwich."
    )

    with coaching._response_agent.override(model=model):
        text = await generate_response(
            "lunch?", {}, user_id="user-1", entries=_peanut_allergy()
        )

    assert text == "Try a turkey sandwich."
    retry = str(seen[1][-1])
    assert "peanut" in retry and "hard restrictions" in retry


async def test_the_reply_guard_replaces_a_reply_that_never_gets_safe():
    model, seen = _scripted_replies("Peanut butter toast is great.")
    session = MagicMock()
    session.add = MagicMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    session.begin.return_value.__aenter__.return_value = None

    with (
        coaching._response_agent.override(model=model),
        patch("backend.agent.coaching.get_session", return_value=factory),
    ):
        text = await generate_response(
            "lunch?", {}, user_id="user-1", entries=_peanut_allergy()
        )

    assert text == get_tunables().safety.reply_guard_fallback_text
    # The reply, then one rewrite per retry.
    assert len(seen) == get_tunables().models.coaching_retries + 1
    row = session.add.call_args.args[0]
    assert (row.outcome, row.user_id) == ("reply_replaced", "user-1")
    assert row.failures[0]["rule"] == "allergen"
    assert row.recipe == {"reply": "Peanut butter toast is great."}


async def test_the_reply_guard_lets_a_patient_without_constraints_through():
    model, seen = _scripted_replies("Peanut butter toast is great.")

    with coaching._response_agent.override(model=model):
        text = await generate_response("lunch?", {}, user_id="user-1", entries=[])

    assert text == "Peanut butter toast is great." and len(seen) == 1


async def test_the_reply_is_replaced_when_the_guard_cannot_run():
    model, _ = _scripted_replies("Anything.")

    with (
        coaching._response_agent.override(model=model),
        patch(
            "backend.agent.coaching.guard_reply_text",
            new_callable=AsyncMock,
            side_effect=FoodDbUnavailable("missing"),
        ),
    ):
        text = await generate_response("lunch?", {}, entries=_peanut_allergy())

    assert text == get_tunables().safety.reply_guard_fallback_text


# ---------------------------------------------------------------------------
# Spec 013 US4: hard facts stated in the turn
# ---------------------------------------------------------------------------

THREAD = "user-1:conv-1"
SHELLFISH = profile.AllergyValue(allergen_group="shellfish")


def _inferred(state: str, **update):
    entry = hard_entry(SHELLFISH, state, source="inferred")
    if state == "confirmed":
        update.setdefault("confirmed_by", "inference")
    return entry.model_copy(update=update)


def _extraction(**kwargs) -> TurnExtraction:
    return TurnExtraction(**kwargs)


def _meal_patches(extraction: TurnExtraction | None):
    suggestion = SuggestionResult(
        message="Rice bowl ...",
        recipe=make_recipe("rice"),
        recommendation_id="rec-1",
        attempts=1,
    )
    return (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=QueryParsed(time_range="today", suggests_meal=True),
        ),
        patch(
            "backend.agent.coaching._extract_facts",
            new_callable=AsyncMock,
            return_value=extraction,
        ),
        patch(
            "backend.agent.coaching.suggest_meal",
            new_callable=AsyncMock,
            return_value=suggestion,
        ),
        patch("backend.agent.readback.profile.mark_readback", new_callable=AsyncMock),
        patch("backend.agent.readback.profile.mark_mentioned", new_callable=AsyncMock),
    )


async def test_a_recipe_is_withheld_when_a_new_fact_needs_confirming(hard_entries):
    pending = _inferred("pending")
    parse, extract, suggest, asked, _ = _meal_patches(_extraction(asked=[pending]))

    with parse, extract, suggest as suggest_mock, asked as asked_mock, _:
        result = await CoachingAgent().handle(
            "user-1", "I'm allergic to shellfish, what's for dinner?", THREAD
        )

    suggest_mock.assert_not_awaited()
    assert result.recipe is None and result.recommendation_id is None
    assert result.message == (
        "Before I suggest a meal, I need to check one thing.\n\n"
        "I'll note this on your profile: Shellfish allergy. Is that right?"
    )
    assert result.readback is not None and result.readback.entry_id == pending.id
    assert result.facts_extracted is True
    asked_mock.assert_awaited_once_with("user-1", [pending.id], THREAD)


async def test_an_unanswered_pending_fact_from_an_earlier_session_is_asked_first(
    hard_entries,
):
    old = _inferred("pending", readback_asked_at=None, conversation_id="user-1:old")
    hard_entries.append(old)
    parse, extract, suggest, asked, _ = _meal_patches(_extraction())

    with parse, extract, suggest as suggest_mock, asked as asked_mock, _:
        result = await CoachingAgent().handle("user-1", "dinner idea?", THREAD)

    suggest_mock.assert_not_awaited()
    assert result.readback is not None and result.readback.entry_id == old.id
    asked_mock.assert_awaited_once_with("user-1", [old.id], THREAD)


async def test_a_fact_already_asked_in_this_conversation_does_not_block_a_recipe(
    hard_entries,
):
    hard_entries.append(
        _inferred(
            "pending", conversation_id=THREAD, readback_asked_at=datetime.now(UTC)
        )
    )
    parse, extract, suggest, asked, _ = _meal_patches(_extraction())

    with parse, extract, suggest as suggest_mock, asked as asked_mock, _:
        result = await CoachingAgent().handle("user-1", "dinner idea?", THREAD)

    suggest_mock.assert_awaited_once()
    assert result.recipe is not None and result.readback is None
    asked_mock.assert_not_awaited()


async def test_an_accepted_fact_binds_the_same_turn_and_is_mentioned_once(
    hard_entries,
):
    accepted = _inferred("confirmed")
    parse, extract, suggest, _, mentioned = _meal_patches(
        _extraction(accepted=[accepted])
    )

    with parse, extract, suggest as suggest_mock, _, mentioned as mentioned_mock:
        result = await CoachingAgent().handle(
            "user-1", "I'm allergic to shellfish", THREAD
        )

    assert accepted in suggest_mock.await_args.args[3]
    assert result.recipe is not None
    assert result.message.endswith(
        "I've noted this on your profile: Shellfish allergy. Tell me if that's wrong."
    )
    assert result.readback is None
    mentioned_mock.assert_awaited_once_with("user-1", accepted.id)


async def test_an_accepted_fact_is_in_the_reply_prompt_and_guard(hard_entries):
    accepted = _inferred("confirmed")
    parsed = QueryParsed(time_range="today", nutrients=["kcal"])

    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching._extract_facts",
            new_callable=AsyncMock,
            return_value=_extraction(accepted=[accepted]),
        ),
        patch(
            "backend.agent.coaching.fetch_data",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="ok",
        ) as gen_mock,
        patch("backend.agent.readback.profile.mark_mentioned", new_callable=AsyncMock),
    ):
        await CoachingAgent().handle("user-1", "I'm allergic to shellfish", THREAD)

    assert "Shellfish allergy" in gen_mock.await_args.kwargs["context_prompt"]
    assert accepted in gen_mock.await_args.kwargs["entries"]


async def test_no_conversation_id_asks_nothing(hard_entries):
    pending = _inferred("pending")
    parse, extract, suggest, asked, _ = _meal_patches(_extraction(asked=[pending]))

    with parse, extract, suggest as suggest_mock, asked as asked_mock, _:
        result = await CoachingAgent().handle("user-1", "dinner idea?")

    suggest_mock.assert_awaited_once()
    asked_mock.assert_not_awaited()
    assert result.message == "Rice bowl ..."


async def test_fact_extraction_runs_alongside_the_query_parse(hard_entries):
    started = asyncio.Event()

    async def parse(*args, **kwargs):
        # Only finishes once extraction has started: sequential code hangs.
        await asyncio.wait_for(started.wait(), timeout=2)
        return QueryParsed(time_range="today", nutrients=["kcal"])

    async def extract(user_id, message, **kwargs):
        started.set()
        return TurnExtraction()

    with (
        patch("backend.agent.coaching.parse_query", parse),
        patch("backend.agent.coaching.extract_turn", extract),
        patch(
            "backend.agent.coaching.fetch_data",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="ok",
        ),
    ):
        result = await CoachingAgent().handle("user-1", "how are my macros?", THREAD)

    assert result.facts_extracted is True


async def test_every_user_gets_the_full_in_turn_extraction(
    hard_entries,
):
    with (
        patch(
            "backend.agent.coaching.extract_turn",
            new_callable=AsyncMock,
            return_value=TurnExtraction(),
        ) as extract_mock,
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=QueryParsed(time_range="today", nutrients=["kcal"]),
        ),
        patch(
            "backend.agent.coaching.fetch_data",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="ok",
        ),
    ):
        result = await CoachingAgent().handle("user-1", "how are my macros?", THREAD)

    extract_mock.assert_awaited_once_with("user-1", "how are my macros?")
    assert result.facts_extracted is True


async def test_a_pending_fact_the_remember_tool_adds_is_read_back_from_the_template(
    hard_entries,
):
    pending = _inferred("pending", created_by="patient")

    async def reply(*args, **kwargs):
        # What memory_tools does when it adds a pending hard entry.
        hard_writes.get().append(True)
        return "Noted, I'll remember that."

    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=QueryParsed(time_range="today", nutrients=["kcal"]),
        ),
        patch(
            "backend.agent.coaching._extract_facts",
            new_callable=AsyncMock,
            return_value=TurnExtraction(),
        ),
        patch(
            "backend.agent.coaching.fetch_data",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch("backend.agent.coaching.generate_response", reply),
        patch(
            "backend.agent.coaching.load_hard_profile",
            new_callable=AsyncMock,
            return_value=[pending],
        ),
        patch(
            "backend.agent.readback.profile.mark_readback", new_callable=AsyncMock
        ) as asked,
    ):
        result = await CoachingAgent().handle(
            "user-1", "please remember I'm allergic to shellfish", THREAD
        )

    assert result.message.startswith("Noted, I'll remember that.")
    assert result.message.endswith("Shellfish allergy. Is that right?")
    assert result.readback is not None and result.readback.entry_id == pending.id
    asked.assert_awaited_once_with("user-1", [pending.id], THREAD)


async def test_a_turn_without_a_tool_write_does_not_reread_the_profile(hard_entries):
    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=QueryParsed(time_range="today", nutrients=["kcal"]),
        ),
        patch(
            "backend.agent.coaching._extract_facts",
            new_callable=AsyncMock,
            return_value=TurnExtraction(),
        ),
        patch(
            "backend.agent.coaching.fetch_data",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="ok",
        ),
        patch(
            "backend.agent.coaching.load_hard_profile",
            new_callable=AsyncMock,
            return_value=[],
        ) as load_mock,
    ):
        await CoachingAgent().handle("user-1", "how are my macros?", THREAD)

    load_mock.assert_awaited_once()  # the turn's own read, not a second one


async def test_a_failed_extraction_does_not_fail_the_turn_and_leaves_celery_to_retry(
    hard_entries,
):
    with (
        patch(
            "backend.agent.coaching.extract_turn",
            new_callable=AsyncMock,
            side_effect=RuntimeError("gemini 429"),
        ),
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=QueryParsed(time_range="today", nutrients=["kcal"]),
        ),
        patch(
            "backend.agent.coaching.fetch_data",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="ok",
        ),
    ):
        result = await CoachingAgent().handle("user-1", "how are my macros?", THREAD)

    assert result.message == "ok"
    assert result.facts_extracted is False
