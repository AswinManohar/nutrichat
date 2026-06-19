"""Shared ingredient-decomposition primitive.

Turns a described composite dish ("chicken biryani") into a list of constituent
ingredient lines with rough gram weights ("150 g basmati rice", "120 g chicken
thigh", …). The lines are designed to feed straight into `extract_entities` →
`usda_lookup_batch`, so resolution/confidence/fallback are unchanged.

Used by the "Break into ingredients" meal action and (by design) the
recipe-import LLM-parse path — one engine, two triggers.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from backend.agent.llm import make_llm
from backend.config import get_tunables

_TUNABLES = get_tunables()


class DecomposeResult(BaseModel):
    """Ingredient lines a dish breaks down into (each parseable by extraction)."""

    ingredients: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


_decompose_llm = make_llm().with_structured_output(DecomposeResult)
_DECOMPOSE_SYSTEM = _TUNABLES.prompts.decompose_system


def decompose_to_ingredients(description: str) -> list[str]:
    """Break a dish description into constituent ingredient lines.

    Args:
        description: Free-text dish, e.g. "chicken biryani for one".

    Returns:
        Ingredient lines with quantities (e.g. "150 g basmati rice"). Empty
        list if the model returns nothing usable — caller should fall back to
        logging the dish as a single item.
    """
    try:
        result = _decompose_llm.invoke(
            [
                {"role": "system", "content": _DECOMPOSE_SYSTEM},
                {"role": "user", "content": description},
            ]
        )
    except Exception:
        return []
    return [line.strip() for line in result.ingredients if line and line.strip()]


def normalize_meal_name(text: str) -> str:
    """Normalize a meal name for exact-match lookup against saved meals.

    Lowercases, strips punctuation, and collapses whitespace so
    "Chicken Biryani!" and "  chicken   biryani " match the same saved meal.

    Args:
        text: Raw meal name or logged phrase.

    Returns:
        Normalized key (may be empty for punctuation-only input).
    """
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


__all__ = ["DecomposeResult", "decompose_to_ingredients", "normalize_meal_name"]
