"""Progress against the patient's nutrient limits, derived from today's meals.

Nothing is stored: every call re-reads today's ``meal_log`` rows (nutrition-day
boundaries from ``core/nutrition_day.py``) and the confirmed limits.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.core.nutrition_day import current_day_bounds
from backend.db.models import MealLog
from backend.db.session import get_session
from backend.safety.profile import (
    HardEntry,
    NutrientLimitValue,
    confirmed,
    limit_text,
    load_hard_profile,
)
from backend.safety.recipe import GRAMS_PER_UNIT, USDA_KEYS

# Limit nutrient -> USDA nutrient key in an item's ``nutrients``, or the
# top-level item field for the two macros.
# Water is grams; treating 1 g as 1 ml is approximate, which the app shows.
_ITEM_FIELDS = {"protein": "protein_g", "carbohydrate": "carbs_g"}


class LimitProgress(BaseModel):
    """One nutrient limit with today's intake against it."""

    entry_id: str
    nutrient: str
    label: str
    amount: float
    min_amount: float | None
    unit: str
    period: str
    so_far: float
    unknown_items: int
    on_track: bool

    model_config = ConfigDict(extra="forbid")


class LimitsToday(BaseModel):
    """Response of GET /profile/limits/today."""

    on_track: int
    total: int
    limits: list[LimitProgress]

    model_config = ConfigDict(extra="forbid")


def item_amount(item: dict, nutrient: str, unit: str) -> float | None:
    """An item's amount of ``nutrient`` in ``unit``, or None when unknown.

    Args:
        item: A meal item as logged (``USDAResult`` fields: macro columns and
            the scaled ``nutrients`` breakdown).
        nutrient: A tracked nutrient key (``recipe.USDA_KEYS`` or protein).
        unit: The unit to return the amount in.
    """
    if nutrient in _ITEM_FIELDS:
        raw, from_unit = item.get(_ITEM_FIELDS[nutrient]), "g"
    else:
        found = (item.get("nutrients") or {}).get(USDA_KEYS.get(nutrient, ""))
        raw, from_unit = (
            (found.get("amount"), found.get("unit")) if found else (None, "")
        )
    factor = GRAMS_PER_UNIT.get((from_unit or "").lower())
    if raw is None or factor is None:
        return None
    return float(raw) * factor / GRAMS_PER_UNIT[unit]


def _progress(
    limit: NutrientLimitValue, entry_id: str, meals: list[list[dict]]
) -> LimitProgress:
    meal_totals: list[float] = []
    unknown = 0
    for items in meals:
        amounts = [item_amount(item, limit.nutrient, limit.unit) for item in items]
        unknown += sum(1 for a in amounts if a is None)
        meal_totals.append(sum(a for a in amounts if a is not None))
    so_far = (
        sum(meal_totals) if limit.period == "per_day" else max(meal_totals, default=0.0)
    )
    text = limit_text(limit)
    return LimitProgress(
        entry_id=entry_id,
        nutrient=limit.nutrient,
        label=f"{text[:1].upper()}{text[1:]}",
        amount=limit.amount,
        min_amount=limit.min_amount,
        unit=limit.unit,
        period=limit.period,
        so_far=round(so_far, 2),
        unknown_items=unknown,
        on_track=so_far <= limit.amount,
    )


async def _todays_meals(user_id: str) -> list[list[dict]]:
    """Today's logged items, one list per meal (nutrition-day boundaries)."""
    start, end = current_day_bounds()
    async with get_session()() as session:
        rows = await session.execute(
            select(MealLog.entities).where(
                MealLog.user_id == user_id,
                MealLog.logged_at >= start,
                MealLog.logged_at < end,
                MealLog.deleted_at.is_(None),
            )
        )
        return [list(r) for r in rows.scalars().all()]


def _limit_entries(entries: list[HardEntry]) -> list[HardEntry]:
    return [e for e in confirmed(entries) if e.type == "nutrient_limit"]


async def intake_today(
    user_id: str, entries: list[HardEntry]
) -> dict[str, LimitProgress]:
    """Today's progress per confirmed nutrient limit, keyed by entry id.

    Used by the recipe checker for per-day limits. Reads ``meal_log`` only
    when the patient has a limit.

    Args:
        user_id: Supabase Auth UUID.
        entries: The patient's hard profile, already loaded.

    Returns:
        Empty when the patient has no confirmed nutrient limit.
    """
    limits = _limit_entries(entries)
    if not limits:
        return {}
    meals = await _todays_meals(user_id)
    return {e.id: _progress(e.value, e.id, meals) for e in limits}


async def limits_today(user_id: str) -> LimitsToday:
    """Progress against every confirmed nutrient limit for today.

    Per-day limits sum today's logged amounts; per-meal limits report the
    highest single meal. ``unknown_items`` counts logged items with no value
    for the nutrient, so the total may be low.

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        How many limits are on track, and each limit's progress.
    """
    progress = list(
        (await intake_today(user_id, await load_hard_profile(user_id))).values()
    )
    return LimitsToday(
        on_track=sum(1 for p in progress if p.on_track),
        total=len(progress),
        limits=progress,
    )
