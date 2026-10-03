"""Boundary models for tracked micronutrients (spec 008 data-model §2–§3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MicroSource = Literal["usda", "estimated", "unknown"]


class MicroValue(BaseModel):
    """One tracked nutrient on one food item, scaled to the item's grams.

    ``amount`` is None exactly when ``source`` is "unknown" — unknown is never
    stored as 0.
    """

    amount: float | None = Field(default=None, ge=0.0)
    source: MicroSource = "unknown"

    model_config = ConfigDict(extra="forbid")


class MealMicro(BaseModel):
    """Meal-level summary of one tracked nutrient (``meal_log.micros[key]``).

    ``total`` sums the known item amounts, ``est`` is the estimated part of
    it, ``known`` counts items with a known value.
    """

    total: float = Field(ge=0.0)
    est: float = Field(ge=0.0)
    known: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid")
