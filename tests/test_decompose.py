"""Unit tests for the ingredient-decomposition primitive + name normalization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agent.tools.decompose import (
    DecomposedIngredient,
    DecomposeResult,
    decompose_to_entities,
    normalize_meal_name,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  Chicken  Biryani! ", "chicken biryani"),
        ("Café Latte", "café latte"),
        ("EGGS, 2", "eggs 2"),
        ("...", ""),
        ("Grilled   Chicken\tSalad", "grilled chicken salad"),
    ],
)
def test_normalize_meal_name(raw: str, expected: str) -> None:
    assert normalize_meal_name(raw) == expected


def test_decompose_builds_entities_and_filters_junk() -> None:
    """Structured ingredients become FoodEntities; blank names / qty<=0 dropped."""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = DecomposeResult(
        ingredients=[
            DecomposedIngredient(food_name="basmati rice", qty_g=150, unit="cup"),
            DecomposedIngredient(food_name="  ", qty_g=10, unit="g"),
            DecomposedIngredient(food_name="chicken thigh", qty_g=120, unit="g"),
            DecomposedIngredient(food_name="water", qty_g=0, unit="g"),
        ]
    )
    with patch("backend.agent.tools.decompose._decompose_llm", mock_llm):
        out = decompose_to_entities("chicken biryani")

    assert [(e.food_name, e.qty_g, e.unit) for e in out] == [
        ("basmati rice", 150, "cup"),
        ("chicken thigh", 120, "g"),
    ]
    # Ingredients are atomic — never re-flagged composite.
    assert all(not e.is_composite for e in out)


def test_decompose_returns_empty_on_llm_error() -> None:
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("LLM down")
    with patch("backend.agent.tools.decompose._decompose_llm", mock_llm):
        out = decompose_to_entities("chicken biryani")
    assert out == []
