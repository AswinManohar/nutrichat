"""A recipe as the generator returns it, and its nutrient totals from USDA data.

The model proposes names and grams; every number the check compares comes from
the bundled USDA database (specs/013 R7), never from the model. An ingredient
the database cannot resolve, or that has no value for a nutrient, makes that
nutrient's total unknown, and the checker fails an unknown total against a limit.

This module must not import ``backend.agent`` (tests/safety/test_boundaries.py),
so :func:`resolve` receives the lookup function from its caller.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.config import get_tunables

Texture = Literal["liquid", "puree", "minced_moist", "soft_bite_sized", "regular"]
Step = Annotated[str, Field(min_length=1, max_length=200)]

# Mass in grams per unit; water counts 1 g as 1 ml (approximate, shown as such).
GRAMS_PER_UNIT = {
    "mg": 0.001,
    "g": 1.0,
    "ml": 1.0,
    "mcg": 0.000001,
    "ug": 0.000001,
    "µg": 0.000001,
}

# Totals computed for every recipe: nutrient -> (USDA nutrient key, unit).
# Protein and kcal come from the food row's own columns instead.
USDA_KEYS = {
    "sodium": "Sodium, Na",
    "potassium": "Potassium, K",
    "phosphorus": "Phosphorus, P",
    "carbohydrate": "Carbohydrate, by difference",
    "fluid": "Water",
    "vitamin_k": "Vitamin K (phylloquinone)",
}
_UNITS = {
    "sodium": "mg",
    "potassium": "mg",
    "phosphorus": "mg",
    "protein": "g",
    "carbohydrate": "g",
    "fluid": "ml",
    "vitamin_k": "mcg",
    "kcal": "kcal",
}
_MACRO_FIELDS = {"protein": "protein_g", "kcal": "kcal"}
# Proximate components (grams per 100 g) that add up to a whole food; the
# mass-balance rule uses them to infer a missing protein or carbohydrate.
_PROXIMATES = (
    "Protein",
    "Total lipid (fat)",
    "Total fat (NLEA)",
    "Carbohydrate, by difference",
    "Water",
    "Ash",
    "Alcohol, ethyl",
)
_INFERABLE = ("protein", "carbohydrate")


class Ingredient(BaseModel):
    """One ingredient: a plain, USDA-searchable name and grams as eaten."""

    name: str = Field(min_length=1, description='e.g. "peanut oil", "rice, cooked"')
    qty_g: float = Field(description="Grams for the whole recipe; ml for drinks")

    model_config = ConfigDict(extra="forbid")


class Recipe(BaseModel):
    """Structured recipe (FR-008). Totals are per serving."""

    name: str = Field(min_length=1)
    intro: str = Field(max_length=200)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=20)
    texture: Texture
    crunchy_or_dry: bool
    steps: list[Step] = Field(min_length=1, max_length=12)
    active_minutes: int = Field(ge=0)
    total_minutes: int = Field(ge=0)
    equipment: list[str] = Field(default_factory=list)
    servings: int = Field(default=1, ge=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _total_covers_active(self) -> Recipe:
        if self.total_minutes < self.active_minutes:
            raise ValueError("total_minutes must be at least active_minutes")
        return self


class ResolvedIngredient(BaseModel):
    """An ingredient matched in the USDA database, or left unresolved."""

    name: str
    qty_g: float
    fdc_id: int | None
    usda_description: str | None
    match_confidence: float
    # Tracked nutrients per 100 g in canonical units; None = unknown.
    per_100g: dict[str, float | None] = Field(default_factory=dict)
    # Nutrients taken as 0 by the mass-balance rule, not read from USDA.
    inferred_zero: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class NutrientTotal(BaseModel):
    """One nutrient's total per serving; ``amount`` None means unknown."""

    nutrient: str
    amount: float | None
    unit: str
    unknown_from: list[str]
    approximate: bool
    # Ingredients whose missing value was taken as 0 (mass balance).
    inferred_zero_from: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class _Lookup(Protocol):
    """The part of ``usda_local.LocalMatch`` that resolution reads."""

    fdc_id: int
    description: str
    match_confidence: float
    macros_per_100g: dict[str, float | None]
    nutrients_per_100g: dict[str, dict]


def malformed_reasons(recipe: Recipe) -> list[str]:
    """Why a parsed recipe is unusable (an ingredient with no positive grams)."""
    return [
        f"{i.name}: quantity must be above 0 g"
        for i in recipe.ingredients
        if i.qty_g <= 0
    ]


def _canonical(amount: Any, unit: Any, target: str) -> float | None:
    """Convert a USDA amount to the canonical unit, or None if not possible."""
    factor = GRAMS_PER_UNIT.get(str(unit or "").lower())
    if amount is None or factor is None:
        return None
    return float(amount) * factor / GRAMS_PER_UNIT[target]


def _per_100g(match: _Lookup) -> tuple[dict[str, float | None], list[str]]:
    """Tracked nutrients per 100 g, and which were inferred to be zero.

    A missing protein or carbohydrate is taken as 0 only when the proximates
    present sum to ``safety.mass_balance_min_g``: the food is then accounted for
    without it. Minerals and vitamin K are never inferred.
    """
    found: dict[str, float | None] = {}
    for nutrient, key in USDA_KEYS.items():
        entry = match.nutrients_per_100g.get(key) or {}
        found[nutrient] = _canonical(
            entry.get("amount"), entry.get("unit"), _UNITS[nutrient]
        )
    for nutrient, field in _MACRO_FIELDS.items():
        value = match.macros_per_100g.get(field)
        found[nutrient] = None if value is None else float(value)
    known = sum(
        float(entry["amount"])
        for key in _PROXIMATES
        if (entry := match.nutrients_per_100g.get(key))
        and entry.get("amount") is not None
        and str(entry.get("unit") or "").lower() == "g"
    )
    inferred: list[str] = []
    if known >= get_tunables().safety.mass_balance_min_g:
        inferred = [n for n in _INFERABLE if found[n] is None]
        found.update(dict.fromkeys(inferred, 0.0))
    return found, inferred


def _resolve_one(
    ingredient: Ingredient, lookup: Callable[[str], _Lookup | None]
) -> ResolvedIngredient:
    floor = get_tunables().usda.match_confidence_floor
    match = lookup(ingredient.name)
    if match is None or match.match_confidence < floor:
        return ResolvedIngredient(
            name=ingredient.name,
            qty_g=ingredient.qty_g,
            fdc_id=None,
            usda_description=None,
            match_confidence=match.match_confidence if match else 0.0,
        )
    per_100g, inferred = _per_100g(match)
    return ResolvedIngredient(
        name=ingredient.name,
        qty_g=ingredient.qty_g,
        fdc_id=match.fdc_id,
        usda_description=match.description,
        match_confidence=match.match_confidence,
        per_100g=per_100g,
        inferred_zero=inferred,
    )


async def resolve(
    recipe: Recipe, lookup: Callable[[str], _Lookup | None]
) -> list[ResolvedIngredient]:
    """Match every ingredient in the local USDA database, in parallel.

    No FDC API call and no model estimate: a match below
    ``usda.match_confidence_floor`` counts as unresolved.

    Args:
        recipe: The generated recipe.
        lookup: ``usda_local.lookup``; blocking, so it runs in worker threads.

    Returns:
        One entry per ingredient, in recipe order.

    Raises:
        Exception: Whatever ``lookup`` raises propagates, in particular
            ``FoodDbUnavailable``; the caller then shows no recipe.
    """
    return list(
        await asyncio.gather(
            *(
                asyncio.to_thread(_resolve_one, ingredient, lookup)
                for ingredient in recipe.ingredients
            )
        )
    )


def totals_for(
    recipe: Recipe, resolved: list[ResolvedIngredient]
) -> list[NutrientTotal]:
    """Per-serving totals; a nutrient is unknown if any ingredient lacks it."""
    totals: list[NutrientTotal] = []
    for nutrient, unit in _UNITS.items():
        amount = 0.0
        unknown: list[str] = []
        for ingredient in resolved:
            per_100g = ingredient.per_100g.get(nutrient)
            if per_100g is None:
                unknown.append(ingredient.name)
            else:
                amount += per_100g * ingredient.qty_g / 100
        totals.append(
            NutrientTotal(
                nutrient=nutrient,
                amount=None if unknown else round(amount / recipe.servings, 2),
                unit=unit,
                unknown_from=unknown,
                approximate=nutrient == "fluid",
                inferred_zero_from=[
                    i.name for i in resolved if nutrient in i.inferred_zero
                ],
            )
        )
    return totals
