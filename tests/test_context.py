from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


from backend.agent.context import (
    ContextBundle,
    GoalSummary,
    WeeklyPattern,
    build_context,
    build_system_prompt,
)
from backend.db.models import UserGoal, UserMemory, WeeklySummary
from backend.db.redis_client import TodayTotals


def _mock_session(*, goal=None, weekly=None, memories=None):
    """Build an async-context-manager session mock for context.py.

    `session.get(UserGoal, ...)` -> goal
    `session.execute(...)` -> result whose `.scalars().first()` -> weekly
                              and `.scalars().all()` -> memories
    """
    session = MagicMock()
    session.get = AsyncMock(return_value=goal)

    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = weekly
    exec_result.scalars.return_value.all.return_value = memories or []
    session.execute = AsyncMock(return_value=exec_result)

    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock(return_value=session)
    return session_factory


async def test_build_context_no_goals_no_history():
    session_factory = _mock_session()

    with (
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
        patch("backend.agent.context.get_session", return_value=session_factory),
    ):
        ctx = await build_context("user-1")

    assert ctx.today_totals.kcal == 0.0
    assert ctx.goals is None
    assert ctx.weekly_pattern is None
    assert ctx.preferences == []


async def test_build_context_populates_goals_and_weekly():
    goal = UserGoal(
        user_id="user-1",
        kcal_goal=2000.0,
        protein_goal=150.0,
        fiber_goal=30.0,
        dietary_prefs={"vegetarian": True},
        streak_days=5,
    )
    weekly = WeeklySummary(
        id="w1",
        user_id="user-1",
        week_start=date(2026, 6, 1),
        avg_protein_g=120.0,
        days_hit_protein=4,
        weak_spots=["fiber"],
        missed_meals=["breakfast"],
    )
    session_factory = _mock_session(goal=goal, weekly=weekly)

    with (
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(kcal=640, protein_g=17, fiber_g=2, n_meals=1),
        ),
        patch("backend.agent.context.get_session", return_value=session_factory),
    ):
        ctx = await build_context("user-1")

    assert ctx.goals == GoalSummary(
        kcal_goal=2000.0,
        protein_goal=150.0,
        fiber_goal=30.0,
        dietary_prefs={"vegetarian": True},
        streak_days=5,
    )
    assert ctx.weekly_pattern == WeeklyPattern(
        avg_protein_g=120.0,
        days_hit_protein=4,
        weak_spots=["fiber"],
        missed_meals=["breakfast"],
    )


async def test_build_context_fetches_preferences_when_message_given():
    memories = [
        UserMemory(
            id="m1",
            user_id="user-1",
            fact="prefers oat milk",
            embedding=[0.1] * 768,
            category="preference",
            confidence=0.9,
        )
    ]
    session_factory = _mock_session(memories=memories)

    with (
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
        patch("backend.agent.context.get_session", return_value=session_factory),
        patch(
            "backend.agent.context._embed_query",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
    ):
        ctx = await build_context("user-1", user_message="what should I eat?")

    assert ctx.preferences == ["prefers oat milk"]


async def test_build_context_skips_preferences_without_message():
    session_factory = _mock_session()

    with (
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
        patch("backend.agent.context.get_session", return_value=session_factory),
        patch(
            "backend.agent.context._embed_query", new_callable=AsyncMock
        ) as embed_mock,
    ):
        ctx = await build_context("user-1")

    embed_mock.assert_not_called()
    assert ctx.preferences == []


def test_build_system_prompt_includes_today_totals():
    ctx = ContextBundle(
        today_totals=TodayTotals(kcal=640, protein_g=17, fiber_g=2, n_meals=1),
    )
    prompt = build_system_prompt(ctx)

    assert "640" in prompt
    assert "17" in prompt


def test_build_system_prompt_stays_within_token_budget():
    ctx = ContextBundle(
        today_totals=TodayTotals(kcal=640, protein_g=17, fiber_g=2, n_meals=1),
        goals=GoalSummary(
            kcal_goal=2000,
            protein_goal=150,
            fiber_goal=30,
            dietary_prefs={},
            streak_days=3,
        ),
        weekly_pattern=WeeklyPattern(
            avg_protein_g=120,
            days_hit_protein=4,
            weak_spots=["fiber"],
            missed_meals=["breakfast"],
        ),
        preferences=["prefers oat milk", "avoids red meat", "likes spicy food"],
    )
    prompt = build_system_prompt(ctx)

    # PRD §5.2 budgets ~456 tokens with prefs; rough estimate of 4 chars/token.
    assert len(prompt) / 4 < 600


def test_build_system_prompt_flags_low_protein():
    ctx = ContextBundle(
        today_totals=TodayTotals(kcal=200, protein_g=10, fiber_g=1, n_meals=1),
        goals=GoalSummary(
            kcal_goal=2000,
            protein_goal=150,
            fiber_goal=30,
            dietary_prefs={},
            streak_days=0,
        ),
    )
    prompt = build_system_prompt(ctx)

    assert "Protein is below 60%" in prompt
