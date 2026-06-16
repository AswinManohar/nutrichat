"""Unit tests for Mindful Eating intake aggregation + safety evaluation."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from backend.agent.tools.mindful import (
    NutrientAmount,
    evaluate_safety,
    get_daily_intake,
)


@pytest.mark.asyncio
async def test_get_daily_intake_merges_macros_and_micros():
    macros = {
        "kcal": 1840.0,
        "protein_g": 72.0,
        "carbs_g": 210.0,
        "fat_g": 60.0,
        "fiber_g": 18.0,
        "n_meals": 3,
    }
    micros = {
        "Sodium, Na": {"amount": 2500.0, "unit": "mg"},
        "Total Sugars": {"amount": 58.0, "unit": "g"},
    }
    with (
        patch(
            "backend.agent.tools.mindful.get_macros_for_range",
            new=AsyncMock(return_value=macros),
        ),
        patch(
            "backend.agent.tools.mindful.get_micronutrients_for_range",
            new=AsyncMock(return_value=micros),
        ),
    ):
        out = await get_daily_intake("user-1", date(2026, 6, 16))

    by_name = {n.name: n for n in out}
    assert by_name["Energy"].amount == 1840.0
    assert by_name["Energy"].unit == "kcal"
    assert by_name["Protein"].amount == 72.0
    # micros mapped from USDA name to display name
    assert by_name["Sodium"].amount == 2500.0
    assert by_name["Total Sugars"].amount == 58.0


def test_evaluate_safety_flags_breaches_with_citation():
    intake = [
        NutrientAmount(name="Sodium", amount=2500.0, unit="mg"),  # UL 2300
        NutrientAmount(name="Total Sugars", amount=58.0, unit="g"),  # UL 50
        NutrientAmount(name="Iron", amount=10.0, unit="mg"),  # UL 45, under
    ]
    alerts = evaluate_safety(intake)
    flagged = {a.nutrient for a in alerts}
    assert flagged == {"Sodium", "Total Sugars"}

    sodium = next(a for a in alerts if a.nutrient == "Sodium")
    assert sodium.limit == 2300.0
    assert sodium.amount == 2500.0
    assert sodium.url.startswith("https://")
    assert "WHO" in sodium.source


def test_evaluate_safety_empty_when_all_under_limits():
    intake = [
        NutrientAmount(name="Sodium", amount=1000.0, unit="mg"),
        NutrientAmount(name="Total Sugars", amount=20.0, unit="g"),
    ]
    assert evaluate_safety(intake) == []


def test_evaluate_safety_fires_exactly_at_limit():
    # UL check is >= : intake exactly at the limit must alert.
    intake = [NutrientAmount(name="Iron", amount=45.0, unit="mg")]
    alerts = evaluate_safety(intake)
    assert len(alerts) == 1 and alerts[0].nutrient == "Iron"


def test_goal_create_mindful_allows_null_targets():
    from backend.api.goals import GoalCreate

    g = GoalCreate(tracking_mode="mindful")
    assert g.tracking_mode == "mindful"
    assert g.kcal_goal is None


def test_goal_create_goals_mode_requires_targets():
    import pytest as _pytest
    from pydantic import ValidationError

    from backend.api.goals import GoalCreate

    with _pytest.raises(ValidationError):
        GoalCreate(tracking_mode="goals", kcal_goal=2000)  # missing protein/fiber


def test_goal_create_goals_mode_with_all_targets_ok():
    from backend.api.goals import GoalCreate

    g = GoalCreate(kcal_goal=2000, protein_goal=120, fiber_goal=30)
    assert g.tracking_mode == "goals"
