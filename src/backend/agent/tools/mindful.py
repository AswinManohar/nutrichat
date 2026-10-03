"""Mindful Eating mode — daily intake aggregation + UL safety evaluation.

A goal-free user still logs meals and gets full nutrient data; this module
computes what they consumed on a given day and flags any nutrient that reaches
or exceeds a research-backed Tolerable Upper Intake Level (the catalogue's
``upper_limit`` entries, config/nutrients.yaml — spec 008).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from backend.agent.tools.history import get_macros_for_range
from backend.config import get_catalog, get_tunables
from backend.nutrients import catalog
from backend.nutrients.daily import get_daily_micros

_TUNABLES = get_tunables()

# Macro columns summed from meal_log, mapped to display name + unit.
_MACRO_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("kcal", "Energy", "kcal"),
    ("protein_g", "Protein", "g"),
    ("carbs_g", "Carbohydrate", "g"),
    ("fat_g", "Fat", "g"),
    ("fiber_g", "Fiber", "g"),
)


class NutrientAmount(BaseModel):
    """One nutrient consumed on a day (absolute amount, no target)."""

    name: str
    amount: float
    unit: str

    model_config = ConfigDict(extra="forbid")


class SafetyAlert(BaseModel):
    """A nutrient whose daily intake reached or exceeded its UL."""

    nutrient: str
    amount: float
    limit: float
    unit: str
    source: str
    url: str

    model_config = ConfigDict(extra="forbid")


def _intake_keys() -> list[str]:
    """Micros shown in Mindful: every key with an upper limit + Check-up keys."""
    keys = [n.key for n in get_catalog().nutrients if n.upper_limit is not None]
    for key in _TUNABLES.nutrient_checkup.keys:
        if key not in keys and catalog.resolve_key(key) == key and key != "fiber":
            keys.append(key)
    return keys


async def get_daily_intake(user_id: str, day: date) -> list[NutrientAmount]:
    """Sum macros and tracked micronutrients consumed on a single day.

    Macros come from the meal_log columns; micronutrients from the meal-level
    summaries via :func:`get_daily_micros` (spec 008), named and united by
    the nutrient catalogue. Unknown nutrients are omitted, never shown as 0.

    Args:
        user_id: Supabase Auth UUID.
        day: Calendar day to aggregate.

    Returns:
        List of NutrientAmount, macros first then micronutrients, omitting any
        micronutrient with no logged amount.
    """
    macros = await get_macros_for_range(user_id, day, day)
    amounts: list[NutrientAmount] = [
        NutrientAmount(name=label, amount=float(macros.get(col, 0.0)), unit=unit)
        for col, label, unit in _MACRO_FIELDS
    ]
    daily = await get_daily_micros(user_id, day, day, keys=_intake_keys())
    for key, value in daily.days[0].values.items():
        nutrient = catalog.nutrient(key)
        amounts.append(
            NutrientAmount(name=nutrient.name, amount=value.total, unit=nutrient.unit)
        )
    return amounts


def evaluate_safety(intake: list[NutrientAmount]) -> list[SafetyAlert]:
    """Flag nutrients whose intake reached or exceeded their UL.

    Args:
        intake: Output of get_daily_intake (matched by catalogue name).

    Returns:
        One SafetyAlert per breached limit (empty if none breached).
    """
    by_name = {n.name: n for n in intake}
    alerts: list[SafetyAlert] = []
    for nutrient in get_catalog().nutrients:
        limit = nutrient.upper_limit
        if limit is None:
            continue
        consumed = by_name.get(nutrient.name)
        if consumed is not None and consumed.amount >= limit.value:
            alerts.append(
                SafetyAlert(
                    nutrient=nutrient.name,
                    amount=consumed.amount,
                    limit=limit.value,
                    unit=nutrient.unit,
                    source=limit.source,
                    url=limit.url,
                )
            )
    return alerts


__all__ = [
    "NutrientAmount",
    "SafetyAlert",
    "evaluate_safety",
    "get_daily_intake",
]
