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
    NutrientLimitValue,
    confirmed,
    limit_text,
    load_hard_profile,
)

# Limit nutrient -> USDA nutrient key in an item's ``nutrients``, or the
# top-level item field for the two macros.
# Water is grams; treating 1 g as 1 ml is approximate, which the app shows.
_USDA_KEYS = {
    "sodium": "Sodium, Na",
    "potassium": "Potassium, K",
    "phosphorus": "Phosphorus, P",
    "fluid": "Water",
}
_ITEM_FIELDS = {"protein": "protein_g", "carbohydrate": "carbs_g"}
_GRAMS_PER_UNIT = {"mg": 0.001, "g": 1.0, "ml": 1.0, "mcg": 0.000001, "ug": 0.000001}


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


def _item_amount(item: dict, limit: NutrientLimitValue) -> float | None:
    """The item's amount of the limited nutrient in the limit's unit, or None."""
    if limit.nutrient in _ITEM_FIELDS:
        raw, unit = item.get(_ITEM_FIELDS[limit.nutrient]), "g"
    else:
        found = (item.get("nutrients") or {}).get(_USDA_KEYS[limit.nutrient])
        raw, unit = (found.get("amount"), found.get("unit")) if found else (None, "")
    factor = _GRAMS_PER_UNIT.get((unit or "").lower())
    if raw is None or factor is None:
        return None
    return float(raw) * factor / _GRAMS_PER_UNIT[limit.unit]


def _progress(
    limit: NutrientLimitValue, entry_id: str, meals: list[list[dict]]
) -> LimitProgress:
    meal_totals: list[float] = []
    unknown = 0
    for items in meals:
        amounts = [_item_amount(item, limit) for item in items]
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
    entries = [
        e
        for e in confirmed(await load_hard_profile(user_id))
        if e.type == "nutrient_limit"
    ]
    if not entries:
        return LimitsToday(on_track=0, total=0, limits=[])
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
        meals = [list(r) for r in rows.scalars().all()]
    limits = [_progress(e.value, e.id, meals) for e in entries]
    return LimitsToday(
        on_track=sum(1 for p in limits if p.on_track), total=len(limits), limits=limits
    )
