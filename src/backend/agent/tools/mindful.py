"""Mindful Eating mode — daily intake aggregation + UL safety evaluation.

A goal-free user still logs meals and gets full nutrient data; this module
computes what they consumed on a given day and flags any nutrient that reaches
or exceeds a research-backed Tolerable Upper Intake Level (see the
``upper_limits`` block in tunables.yaml).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from backend.agent.tools.history import (
    get_macros_for_range,
    get_micronutrients_for_range,
)
from backend.config import get_tunables

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


async def get_daily_intake(user_id: str, day: date) -> list[NutrientAmount]:
    """Sum macros and tracked micronutrients consumed on a single day.

    Macros come from the meal_log columns; everything else (sugar, saturated
    fat, sodium, vitamins, minerals) is summed from the per-item ``nutrients``
    JSONB via the USDA names declared in the ``upper_limits`` and
    ``nutrient_checkup.micronutrients`` tunables. LLM-estimated items
    contribute macros but not micros (existing behaviour).

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

    # USDA name -> display name, de-duplicated across both tunable blocks.
    usda_to_display: dict[str, str] = {}
    for display, entry in _TUNABLES.upper_limits.items():
        usda_to_display.setdefault(entry.usda_name, display)
    for display, entry in _TUNABLES.nutrient_checkup.micronutrients.items():
        usda_to_display.setdefault(entry.usda_name, display)

    micros = await get_micronutrients_for_range(
        user_id, day, day, list(usda_to_display.keys())
    )
    for usda_name, data in micros.items():
        amounts.append(
            NutrientAmount(
                name=usda_to_display.get(usda_name, usda_name),
                amount=float(data["amount"]),
                unit=str(data["unit"]),
            )
        )
    return amounts


def evaluate_safety(intake: list[NutrientAmount]) -> list[SafetyAlert]:
    """Flag nutrients whose intake reached or exceeded their UL.

    Args:
        intake: Output of get_daily_intake (matched by display name).

    Returns:
        One SafetyAlert per breached limit (empty if none breached).
    """
    by_name = {n.name: n for n in intake}
    alerts: list[SafetyAlert] = []
    for display, entry in _TUNABLES.upper_limits.items():
        consumed = by_name.get(display)
        if consumed is not None and consumed.amount >= entry.ul:
            alerts.append(
                SafetyAlert(
                    nutrient=display,
                    amount=consumed.amount,
                    limit=entry.ul,
                    unit=entry.unit,
                    source=entry.source,
                    url=entry.url,
                )
            )
    return alerts


__all__ = [
    "NutrientAmount",
    "SafetyAlert",
    "evaluate_safety",
    "get_daily_intake",
]
