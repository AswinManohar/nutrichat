"""Unit tests for meal-category mapping and normalization."""

from __future__ import annotations

import pytest

from backend.agent.tools.meals import (
    MEAL_CATEGORIES,
    _meal_type_from_hour,
    normalize_meal_type,
)


@pytest.mark.parametrize(
    "hour,expected",
    [
        (0, "snack"),
        (4, "snack"),
        (5, "breakfast"),
        (10, "breakfast"),
        (11, "brunch"),
        (12, "lunch"),
        (14, "lunch"),
        (15, "snack"),
        (16, "snack"),
        (17, "dinner"),
        (21, "dinner"),
        (22, "snack"),
        (23, "snack"),
    ],
)
def test_meal_type_from_hour_boundaries(hour: int, expected: str) -> None:
    assert _meal_type_from_hour(hour) == expected


def test_meal_type_from_hour_always_valid() -> None:
    for hour in range(24):
        assert _meal_type_from_hour(hour) in MEAL_CATEGORIES


@pytest.mark.parametrize(
    "value",
    ["breakfast", "Lunch", "  DINNER  ", "snack", "brunch"],
)
def test_normalize_meal_type_accepts_valid(value: str) -> None:
    assert normalize_meal_type(value) == value.strip().lower()


@pytest.mark.parametrize("value", [None, "", "supper", "second breakfast", "xyz"])
def test_normalize_meal_type_falls_back_to_clock(value: str | None) -> None:
    # Junk/missing values fall back to a valid clock-inferred category.
    assert normalize_meal_type(value) in MEAL_CATEGORIES
