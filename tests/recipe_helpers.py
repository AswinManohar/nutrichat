"""Builders for recipes and USDA-resolved ingredients used by safety tests."""

from __future__ import annotations

from typing import Any

from backend.safety.limits import LimitProgress
from backend.safety.recipe import Ingredient, Recipe, ResolvedIngredient

_NUTRIENTS = (
    "sodium",
    "potassium",
    "phosphorus",
    "protein",
    "carbohydrate",
    "fluid",
    "vitamin_k",
    "kcal",
)


def make_recipe(*names: str, **overrides: Any) -> Recipe:
    """A valid recipe of 100 g of each named ingredient."""
    fields: dict[str, Any] = {
        "name": "Test dish",
        "intro": "A simple dish.",
        "ingredients": [Ingredient(name=n, qty_g=100) for n in names or ("rice",)],
        "texture": "regular",
        "crunchy_or_dry": False,
        "steps": ["Cook everything."],
        "active_minutes": 10,
        "total_minutes": 20,
        "equipment": [],
        "servings": 1,
    }
    return Recipe(**{**fields, **overrides})


def resolved(
    name: str,
    *,
    qty_g: float = 100,
    description: str | None = None,
    unresolved: bool = False,
    **per_100g: float | None,
) -> ResolvedIngredient:
    """An ingredient as USDA resolution would return it (all nutrients 0 unless set)."""
    if unresolved:
        return ResolvedIngredient(
            name=name,
            qty_g=qty_g,
            fdc_id=None,
            usda_description=None,
            match_confidence=0.0,
        )
    return ResolvedIngredient(
        name=name,
        qty_g=qty_g,
        fdc_id=1,
        usda_description=description or name,
        match_confidence=1.0,
        per_100g={**dict.fromkeys(_NUTRIENTS, 0.0), **per_100g},
    )


def progress(entry_id: str, so_far: float, *, unknown_items: int = 0) -> LimitProgress:
    """Today's progress against one limit entry."""
    return LimitProgress(
        entry_id=entry_id,
        nutrient="sodium",
        label="Sodium",
        amount=1.0,
        min_amount=None,
        unit="mg",
        period="per_day",
        so_far=so_far,
        unknown_items=unknown_items,
        on_track=True,
    )
