from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.context import (
    ContextBundle,
    GoalSummary,
    WeeklyPattern,
    build_context,
    build_restrictions_prompt,
    build_system_prompt,
    load_restrictions,
)
from backend.agent.meal_history import (
    EatenMeal,
    SuggestedMeal,
    build_history_block,
    render_history_block,
)
from backend.agent.memory import MemoryFact
from backend.db.models import UserGoal, WeeklySummary
from backend.db.redis_client import TodayTotals
from backend.safety import profile
from backend.safety.profile import HardEntry
from tests.profile_helpers import hard_entry


@pytest.fixture(autouse=True)
def soft_context() -> Iterator[None]:
    """No soft profile or staples unless a test patches them in."""
    with (
        patch(
            "backend.agent.context.load_profile",
            AsyncMock(return_value=[]),
        ),
        patch("backend.agent.context.fetch_staples", AsyncMock(return_value={})),
    ):
        yield


@pytest.fixture(autouse=True)
def hard_entries() -> Iterator[list[HardEntry]]:
    """The user's live hard profile; empty unless a test fills it."""
    entries: list[HardEntry] = []
    with patch(
        "backend.agent.context.hard_profile.load_hard_profile",
        AsyncMock(return_value=entries),
    ):
        yield entries


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
    assert ctx.profile == []


async def test_build_context_populates_goals_and_weekly():
    goal = UserGoal(
        user_id="user-1",
        kcal_goal=2000.0,
        protein_goal=150.0,
        fiber_goal=30.0,
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
        streak_days=5,
    )
    assert ctx.weekly_pattern == WeeklyPattern(
        avg_protein_g=120.0,
        days_hit_protein=4,
        weak_spots=["fiber"],
        missed_meals=["breakfast"],
    )


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
            streak_days=3,
        ),
        weekly_pattern=WeeklyPattern(
            avg_protein_g=120,
            days_hit_protein=4,
            weak_spots=["fiber"],
            missed_meals=["breakfast"],
        ),
        profile=[
            _fact("oat milk only", "like"),
            _fact("red meat", "dislike"),
            _fact("spicy food", "like"),
        ],
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
            streak_days=0,
        ),
    )
    prompt = build_system_prompt(ctx)

    assert "Protein is below 60%" in prompt


def _fact(text: str, kind: str) -> MemoryFact:
    return MemoryFact(id=text, fact=text, kind=kind, source="stated")


async def test_build_context_loads_the_whole_profile_for_every_user():
    session_factory = _mock_session()
    facts = [_fact("Mushrooms", "dislike")]

    with (
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
        patch("backend.agent.context.get_session", return_value=session_factory),
        patch(
            "backend.agent.context.load_profile",
            new_callable=AsyncMock,
            return_value=facts,
        ) as load,
        patch(
            "backend.agent.context.fetch_staples",
            new_callable=AsyncMock,
            return_value={"breakfast": ["Oats"]},
        ),
    ):
        # No message: the profile does not depend on one.
        ctx = await build_context("user-1")

    load.assert_awaited_once_with("user-1")
    assert ctx.profile == facts
    assert ctx.staples == {"breakfast": ["Oats"]}


def test_build_system_prompt_renders_hard_block_then_soft_profile():
    ctx = ContextBundle(
        today_totals=TodayTotals(),
        hard_block="Patient safety profile (confirmed by the patient):\n- X",
        profile=[_fact("Mushrooms", "dislike")],
        staples={"breakfast": ["Oats"]},
    )

    prompt = build_system_prompt(ctx)

    assert "Patient safety profile" in prompt
    assert "- Dislikes (avoid): Mushrooms" in prompt
    assert "breakfast: Oats" in prompt
    # Hard block first, both before the accountability rules.
    assert prompt.index("Patient safety profile") < prompt.index("Mushrooms")
    assert prompt.index("Mushrooms") < prompt.index("Accountability rules:")


def test_build_system_prompt_empty_profile_adds_no_block():
    ctx = ContextBundle(today_totals=TodayTotals())

    assert "Long-term profile" not in build_system_prompt(ctx)


async def test_hard_block_is_built_without_any_soft_profile(hard_entries):
    # FR-004: the binding profile does not depend on the soft profile.
    hard_entries += [
        hard_entry(profile.AllergyValue(allergen_group="peanut")),
        hard_entry(profile.DietSettingValue(setting="vegetarian")),
        hard_entry(profile.DietSettingValue(setting="no_nuts")),
        hard_entry(profile.DiagnosisValue(condition="diabetes")),
    ]
    with (
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
        patch("backend.agent.context.get_session", return_value=_mock_session()),
    ):
        ctx = await build_context("user-1")

    prompt = build_system_prompt(ctx)
    assert "Allergies (never serve, including derived ingredients): Peanut allergy" in (
        prompt
    )
    assert "Diet settings (binding): no nuts, vegetarian" in prompt
    assert "Declared health conditions: diabetes." in prompt


async def test_pending_entries_are_listed_as_not_applied(hard_entries):
    hard_entries += [hard_entry(profile.DietSettingValue(setting="vegan"), "pending")]
    with (
        patch("backend.agent.context.get_session", return_value=_mock_session()),
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
    ):
        prompt = build_system_prompt(await build_context("user-1"))

    assert "Awaiting confirmation, do not apply until the patient confirms: Vegan" in (
        prompt
    )
    assert "Diet settings (binding)" not in prompt


async def test_build_context_fails_when_the_hard_profile_cannot_load():
    with (
        patch(
            "backend.agent.context.hard_profile.load_hard_profile",
            AsyncMock(side_effect=OSError("postgres down")),
        ),
        patch("backend.agent.context.get_session", return_value=_mock_session()),
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
        pytest.raises(OSError),
    ):
        await build_context("user-1")


async def test_build_context_fails_when_the_profile_is_too_large(hard_entries):
    cap = 2
    hard_entries += [
        hard_entry(profile.FoodExclusionValue(terms=[f"food {i}"]))
        for i in range(cap + 1)
    ]
    tunables = MagicMock()
    tunables.safety.hard_profile_max_entries = cap
    with (
        patch("backend.safety.profile.get_tunables", return_value=tunables),
        patch("backend.agent.context.get_session", return_value=_mock_session()),
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
        pytest.raises(profile.ProfileTooLarge),
    ):
        await build_context("user-1")


async def test_load_restrictions_reads_goal_row_and_hard_profile(hard_entries):
    goal = UserGoal(
        user_id="user-1",
        kcal_goal=2000.0,
        protein_goal=120.0,
        fiber_goal=30.0,
        streak_days=2,
    )
    hard_entries += [
        hard_entry(profile.DietSettingValue(setting="vegan")),
        hard_entry(profile.DiagnosisValue(condition="hypertension")),
        hard_entry(profile.FoodExclusionValue(terms=["pork"])),
    ]
    load = AsyncMock()
    with (
        patch(
            "backend.agent.context.get_session", return_value=_mock_session(goal=goal)
        ),
        patch("backend.agent.context.load_profile", load),
    ):
        ctx = await load_restrictions("user-1")

    load.assert_not_awaited()
    prompt = build_restrictions_prompt(ctx)
    assert "Diet settings (binding): vegan" in prompt
    assert "Declared health conditions: high blood pressure." in prompt
    assert "Never suggest (hard restrictions): No pork" in prompt
    assert "Goals: 2000 kcal, 120g protein, 30g fiber." in prompt
    assert "Hard constraints:" in prompt
    assert "Today so far" not in prompt


async def test_load_restrictions_fails_when_the_hard_profile_cannot_load():
    with (
        patch("backend.agent.context.get_session", return_value=_mock_session()),
        patch(
            "backend.agent.context.hard_profile.load_hard_profile",
            AsyncMock(side_effect=OSError("postgres down")),
        ),
        pytest.raises(OSError),
    ):
        await load_restrictions("user-1")


# --- three-week meal history (spec 013 FR-026, FR-027) ------------------------


def _suggested(name: str, status: str = "shown", reason: str | None = None):
    return SuggestedMeal(
        recommendation_id=name,
        name=name,
        status=status,
        rejection_reason=reason,
        created_at=datetime(2026, 11, 10, tzinfo=UTC),
    )


def _eaten(label: str) -> EatenMeal:
    return EatenMeal(label=label, logged_at=datetime(2026, 11, 11, tzinfo=UTC))


def test_history_block_lists_suggested_then_eaten_meals() -> None:
    block = render_history_block(
        [_suggested("Lemon chicken", "rejected", "too bland")],
        [_eaten("Oatmeal with banana")],
        days=21,
        max_lines=30,
    )

    assert block.splitlines() == [
        "Meals from the last 21 days (do not repeat these without being asked):",
        "- Lemon chicken (suggested, rejected: too bland)",
        "- Oatmeal with banana (eaten)",
    ]


def test_history_block_drops_duplicates_keeping_the_suggestion_status() -> None:
    block = render_history_block(
        [_suggested("Lemon Chicken", "rejected"), _suggested("lemon chicken")],
        [_eaten("lemon chicken!"), _eaten("Oats"), _eaten("oats")],
        days=21,
        max_lines=30,
    )

    assert block.count("\n") == 2
    assert "- Lemon Chicken (suggested, rejected)" in block
    assert "- Oats (eaten)" in block


def test_history_block_is_capped_at_the_line_limit() -> None:
    block = render_history_block(
        [_suggested(f"Dish {i}") for i in range(40)], [], days=21, max_lines=30
    )

    assert len(block.splitlines()) == 1 + 30


def test_history_block_is_empty_without_history() -> None:
    assert render_history_block([], [], days=21, max_lines=30) == ""


async def test_history_block_is_omitted_and_logged_when_the_read_fails(caplog) -> None:
    with (
        patch(
            "backend.agent.meal_history.load_suggested",
            AsyncMock(side_effect=OSError("postgres down")),
        ),
        patch("backend.agent.meal_history.load_eaten", AsyncMock(return_value=[])),
        caplog.at_level(logging.WARNING),
    ):
        block = await build_history_block("user-1")

    assert block == ""
    assert "meal history unavailable" in caplog.text


async def test_history_block_reads_the_configured_window() -> None:
    suggested = AsyncMock(return_value=[_suggested("Soup")])
    with (
        patch("backend.agent.meal_history.load_suggested", suggested),
        patch("backend.agent.meal_history.load_eaten", AsyncMock(return_value=[])),
    ):
        block = await build_history_block("user-1")

    suggested.assert_awaited_once_with("user-1", 21, 30)
    assert "- Soup (suggested, shown)" in block


async def test_build_context_omits_the_soft_profile_when_it_cannot_be_read(
    hard_entries, caplog
):
    hard_entries.append(hard_entry(profile.AllergyValue(allergen_group="peanut")))
    with (
        patch(
            "backend.agent.context.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(),
        ),
        patch("backend.agent.context.get_session", return_value=_mock_session()),
        patch(
            "backend.agent.context.load_profile",
            AsyncMock(side_effect=OSError("postgres down")),
        ),
        caplog.at_level(logging.WARNING),
    ):
        ctx = await build_context("user-1")

    assert ctx.profile == []
    assert "Peanut allergy" in build_system_prompt(ctx)
    assert "soft profile unavailable" in caplog.text
