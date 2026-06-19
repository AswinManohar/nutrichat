"""Unit tests for the ingredient-decomposition primitive + name normalization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agent.tools.decompose import (
    DecomposeResult,
    decompose_to_ingredients,
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


def test_decompose_strips_and_filters_blank_lines() -> None:
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = DecomposeResult(
        ingredients=["150 g basmati rice", "  ", "120 g chicken thigh", ""]
    )
    with patch("backend.agent.tools.decompose._decompose_llm", mock_llm):
        out = decompose_to_ingredients("chicken biryani")
    assert out == ["150 g basmati rice", "120 g chicken thigh"]


def test_decompose_returns_empty_on_llm_error() -> None:
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("LLM down")
    with patch("backend.agent.tools.decompose._decompose_llm", mock_llm):
        out = decompose_to_ingredients("chicken biryani")
    assert out == []
