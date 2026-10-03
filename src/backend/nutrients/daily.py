"""Per-day micronutrient totals computed from logged meals (never stored).

The single read path for tracked micronutrients (spec 008 FR-017, FR-018):
the Check-up, Mindful panel, coaching and ``GET /nutrients/daily`` all go
through :func:`get_daily_micros`, so they can never disagree (SC-006).

One SQL pass loads the range's meals; each meal's summary is computed from
its items' stored micros (``entities[].micros``, the only copy) and added up
in Python. Fiber comes from the ``meal_log.fiber_g`` column and salt is
derived from sodium — neither is stored in item micros.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from backend.config import NutrientDef, get_catalog
from backend.core.nutrition_day import NUTRITION_DATE_SQL, sql_day_params
from backend.db.session import get_session
from backend.nutrients.models import MealMicro
from backend.nutrients.resolve import from_stored, summarise, summarise_items

MAX_RANGE_DAYS = 365
_ROUND = 4


class FoodContribution(BaseModel):
    """One logged food's values within a meal (spec 004 top contributors)."""

    food_name: str
    values: dict[str, MealMicro]

    model_config = ConfigDict(extra="forbid")


class MealContribution(BaseModel):
    """One meal's share of a day's totals (``meals=true``)."""

    meal_id: str
    meal_type: str
    label: str | None = None
    values: dict[str, MealMicro]
    foods: list[FoodContribution] = []

    model_config = ConfigDict(extra="forbid")


class DayMicros(BaseModel):
    """One nutrition day. ``logged`` false means "no data", not zero."""

    date: date
    logged: bool
    n_meals: int = Field(ge=0)
    items: int = Field(ge=0)
    values: dict[str, MealMicro]
    meals: list[MealContribution] | None = None

    model_config = ConfigDict(extra="forbid")


class DailyMicrosResponse(BaseModel):
    """Every day in ``[from, to]`` (contracts/daily-totals.md)."""

    from_: date = Field(alias="from", serialization_alias="from")
    to: date
    days: list[DayMicros]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _active_defs() -> dict[str, NutrientDef]:
    return {n.key: n for n in get_catalog().nutrients if n.status == "active"}


def validate_request(
    date_from: date, date_to: date, keys: list[str] | None
) -> list[str]:
    """Check the range and keys; return the keys to compute.

    Raises:
        ValueError: If the range is inverted or longer than 365 days, or a key
            is not an active catalogue key.
    """
    if date_to < date_from:
        raise ValueError("'to' is before 'from'")
    if (date_to - date_from).days >= MAX_RANGE_DAYS:
        raise ValueError(f"range is longer than {MAX_RANGE_DAYS} days")
    defs = _active_defs()
    if keys is None:
        return list(defs)
    unknown = [k for k in keys if k not in defs]
    if unknown:
        raise ValueError(f"unknown nutrient keys: {unknown}")
    return list(dict.fromkeys(keys))


def _meal_values(
    micros: dict, fiber_g: float, items: int, keys: list[str]
) -> dict[str, MealMicro]:
    """Values for one meal: stored summary, fiber column, derived salt."""
    defs = _active_defs()
    out: dict[str, MealMicro] = {}
    for key in keys:
        d = defs[key]
        if d.column is not None:
            if items:
                out[key] = MealMicro(total=fiber_g or 0.0, est=0.0, known=items)
        elif d.derived is not None:
            src = micros.get(d.derived.source_key)
            if src:
                f = d.derived.factor
                out[key] = MealMicro(
                    total=round(src["total"] * f, _ROUND),
                    est=round(src["est"] * f, _ROUND),
                    known=src["known"],
                )
        elif key in micros:
            out[key] = MealMicro.model_validate(micros[key])
    return out


def _add(acc: dict[str, MealMicro], values: dict[str, MealMicro]) -> None:
    for key, v in values.items():
        prev = acc.get(key)
        acc[key] = (
            v
            if prev is None
            else MealMicro(
                total=round(prev.total + v.total, _ROUND),
                est=round(prev.est + v.est, _ROUND),
                known=prev.known + v.known,
            )
        )


async def get_daily_micros(
    user_id: str,
    date_from: date,
    date_to: date,
    keys: list[str] | None = None,
    include_meals: bool = False,
) -> DailyMicrosResponse:
    """Per-day totals for a user and range (contracts/daily-totals.md).

    Args:
        user_id: Supabase Auth UUID.
        date_from: First nutrition day (inclusive).
        date_to: Last nutrition day (inclusive); at most 364 days after
            ``date_from``.
        keys: Catalogue keys to compute; None means every active key.
        include_meals: Also return per-meal contributions.

    Returns:
        One DayMicros per day in the range, empty days marked not logged.

    Raises:
        ValueError: On an invalid range or unknown key (see validate_request).
    """
    wanted = validate_request(date_from, date_to, keys)
    async with get_session()() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT " + NUTRITION_DATE_SQL + " AS day, meal_id::text AS "
                    "meal_id, meal_type, label, fiber_g, entities "
                    "FROM meal_log WHERE user_id = :user_id "
                    "AND deleted_at IS NULL "
                    "AND " + NUTRITION_DATE_SQL + " BETWEEN :date_from AND :date_to "
                    "ORDER BY logged_at"
                ),
                {
                    "user_id": user_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    **sql_day_params(),
                },
            )
        ).all()

    by_day: dict[date, list] = {}
    for row in rows:
        by_day.setdefault(row.day, []).append(row)

    days: list[DayMicros] = []
    current = date_from
    while current <= date_to:
        meals = by_day.get(current, [])
        totals: dict[str, MealMicro] = {}
        contributions: list[MealContribution] = []
        n_items = 0
        for row in meals:
            items = row.entities
            if isinstance(items, str):  # some JSONB paths return text
                items = json.loads(items or "[]")
            items = items if isinstance(items, list) else []
            n_items += len(items)
            values = _meal_values(
                summarise_items(items), row.fiber_g, len(items), wanted
            )
            _add(totals, values)
            if include_meals:
                contributions.append(
                    MealContribution(
                        meal_id=row.meal_id,
                        meal_type=row.meal_type,
                        label=row.label,
                        values=values,
                        foods=[
                            FoodContribution(
                                food_name=str(item.get("food_name", "")),
                                values=_meal_values(
                                    summarise([from_stored(item.get("micros"))]),
                                    float(item.get("fiber_g") or 0.0),
                                    1,
                                    wanted,
                                ),
                            )
                            for item in items
                        ],
                    )
                )
        days.append(
            DayMicros(
                date=current,
                logged=bool(meals),
                n_meals=len(meals),
                items=n_items,
                values=totals,
                meals=contributions if include_meals else None,
            )
        )
        current += timedelta(days=1)
    return DailyMicrosResponse(from_=date_from, to=date_to, days=days)


def range_totals(resp: DailyMicrosResponse) -> dict[str, MealMicro]:
    """Sum a response's days into one total per key (for range readers)."""
    acc: dict[str, MealMicro] = {}
    for day in resp.days:
        _add(acc, day.values)
    return acc


__all__ = [
    "DailyMicrosResponse",
    "FoodContribution",
    "DayMicros",
    "MealContribution",
    "get_daily_micros",
    "range_totals",
    "validate_request",
]
