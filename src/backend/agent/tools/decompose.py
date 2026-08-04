"""Shared ingredient-decomposition primitive.

Turns a described composite dish ("chicken biryani") into a list of constituent
ingredient FoodEntities with rough gram weights (150 g basmati rice, 120 g
chicken thigh, …), ready to feed straight into `usda_lookup_batch`.

The model emits structured ingredients (food_name + gram weight) directly, so
no second `extract_entities` pass is needed to re-parse text lines — one LLM
call per dish instead of two.

Used by the "Break into ingredients" meal action and the automatic
composite-dish decomposition in the meal graph — one engine, two triggers.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from backend.agent.llm import make_llm
from backend.agent.tools.meals import FoodEntity
from backend.config import get_tunables

_TUNABLES = get_tunables()


class DecomposedIngredient(BaseModel):
    """One constituent ingredient of a dish, with a gram weight."""

    food_name: str = Field(
        description="Specific, USDA-searchable ingredient name, e.g. 'chicken thigh'"
    )
    qty_g: float = Field(
        description="Gram weight of this ingredient for the portion described"
    )
    unit: str = Field(
        default="g",
        description="Original unit if the user thinks in it (cup, tbsp, piece); else g",
    )

    model_config = ConfigDict(extra="forbid")


class DecomposeResult(BaseModel):
    """Structured ingredient breakdown a dish decomposes into."""

    ingredients: list[DecomposedIngredient] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


_decompose_llm = make_llm().with_structured_output(DecomposeResult)
_DECOMPOSE_SYSTEM = _TUNABLES.prompts.decompose_system


def decompose_to_entities(description: str) -> list[FoodEntity]:
    """Break a dish description into constituent ingredient FoodEntities.

    Args:
        description: Free-text dish, e.g. "chicken biryani for one".

    Returns:
        FoodEntity list with gram weights, each flagged is_composite=False
        (ingredients are atomic). Empty list if the model returns nothing
        usable — caller should fall back to logging the dish as a single item.
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
    entities: list[FoodEntity] = []
    for ing in result.ingredients:
        name = ing.food_name.strip()
        if not name or ing.qty_g <= 0:
            continue
        entities.append(
            FoodEntity(
                food_name=name,
                qty_g=ing.qty_g,
                unit=(ing.unit or "g").strip() or "g",
                is_composite=False,
            )
        )
    return entities


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


__all__ = [
    "DecomposeResult",
    "DecomposedIngredient",
    "decompose_to_entities",
    "normalize_meal_name",
]
