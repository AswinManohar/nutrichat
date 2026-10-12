from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy import text as sa_text

from backend.config import get_tunables
from backend.core.nutrition_day import (
    NUTRITION_DATE_SQL,
    nutrition_today,
    sql_day_params,
)
from backend.db.models import MealLog
from backend.db.session import get_session

_TUNABLES = get_tunables()
_CHECKUP_MICRONUTRIENTS = _TUNABLES.nutrient_checkup.micronutrients
_CHECKUP_FLAT_THRESHOLD = _TUNABLES.nutrient_checkup.flat_threshold_pct
_CHECKUP_RDA = _TUNABLES.nutrient_checkup.rda

_STAPLES_WINDOW_DAYS = _TUNABLES.memory.staples_window_days
_STAPLES_MIN_COUNT = _TUNABLES.memory.staples_min_count
# Output bounds for get_staple_foods: it feeds the coaching prompt, so its
# size must not grow with the user's history.
_STAPLES_PER_MEAL_TYPE = 5
_STAPLE_NAME_MAX_CHARS = 40
_STAPLE_MEAL_ORDER = ("breakfast", "lunch", "dinner", "snack")

# Display name -> (meal_log column, unit) for the macro nutrients in the
# Daily Nutrient Check-up. Sugar and vitamins/minerals come from
# _CHECKUP_MICRONUTRIENTS instead (entities[].nutrients, USDA names).
_CHECKUP_MACROS: dict[str, tuple[str, str]] = {
    "Protein": ("protein_g", "g"),
    "Fiber": ("fiber_g", "g"),
}


async def get_macros_for_range(
    user_id: str, date_from: date, date_to: date
) -> dict[str, float]:
    """Sum macros from `meal_log` over an inclusive date range.

    Used by the coaching agent for any range other than "today" (today's
    macros come from Redis via get_today_totals).

    Args:
        user_id: Supabase Auth UUID.
        date_from: Start of the range (inclusive).
        date_to: End of the range (inclusive).

    Returns:
        Dict with kcal, protein_g, carbs_g, fat_g, fiber_g, n_meals. All
        zero if no meals were logged in the range.
    """
    async with get_session()() as session:
        result = await session.execute(
            sa_text(
                "SELECT "
                "COALESCE(SUM(kcal), 0) AS kcal, "
                "COALESCE(SUM(protein_g), 0) AS protein_g, "
                "COALESCE(SUM(carbs_g), 0) AS carbs_g, "
                "COALESCE(SUM(fat_g), 0) AS fat_g, "
                "COALESCE(SUM(fiber_g), 0) AS fiber_g, "
                "COUNT(*) AS n_meals "
                "FROM meal_log "
                "WHERE user_id = :user_id "
                "AND " + NUTRITION_DATE_SQL + " BETWEEN :date_from AND :date_to"
            ),
            {
                "user_id": user_id,
                "date_from": date_from,
                "date_to": date_to,
                **sql_day_params(),
            },
        )
        row = result.one()

    return {
        "kcal": float(row.kcal),
        "protein_g": float(row.protein_g),
        "carbs_g": float(row.carbs_g),
        "fat_g": float(row.fat_g),
        "fiber_g": float(row.fiber_g),
        "n_meals": int(row.n_meals),
    }


async def get_micronutrients_for_range(
    user_id: str, date_from: date, date_to: date, nutrient_names: list[str]
) -> dict[str, dict[str, float | str]]:
    """Sum micronutrient totals from `meal_log.entities` JSONB over a range.

    Unnests each meal's `entities` array (one element per logged food item,
    each with a `nutrients` dict keyed by USDA nutrient name) and sums the
    requested nutrients.

    Args:
        user_id: Supabase Auth UUID.
        date_from: Start of the range (inclusive).
        date_to: End of the range (inclusive).
        nutrient_names: USDA nutrient names to sum, e.g.
            ["Vitamin B-12", "Iron, Fe"].

    Returns:
        Dict keyed by nutrient name, mapping to {"amount": total, "unit":
        unit}. Nutrients not found in any logged item are omitted.
    """
    results: dict[str, dict[str, float | str]] = {}
    async with get_session()() as session:
        for nutrient in nutrient_names:
            result = await session.execute(
                sa_text(
                    "SELECT "
                    "SUM((item->'nutrients'->:nutrient->>'amount')::float) AS total, "
                    "MAX(item->'nutrients'->:nutrient->>'unit') AS unit "
                    "FROM meal_log, "
                    "jsonb_array_elements(entities) AS item "
                    "WHERE user_id = :user_id "
                    "AND " + NUTRITION_DATE_SQL + " BETWEEN :date_from AND :date_to "
                    "AND item->'nutrients' ? :nutrient"
                ),
                {
                    "user_id": user_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "nutrient": nutrient,
                    **sql_day_params(),
                },
            )
            row = result.one()
            if row.total is not None:
                results[nutrient] = {"amount": float(row.total), "unit": row.unit}

    return results


def _trend(cur_avg: float, prev_avg: float) -> tuple[float | None, str]:
    """Compute trend_pct and up/down/flat direction vs the prior week.

    Returns (None, "flat") if both weeks are zero, (None, "up") if only the
    prior week is zero (no baseline to divide by), and otherwise the percent
    change with "flat" applied when it falls within
    ``nutrient_checkup.flat_threshold_pct``.
    """
    if prev_avg == 0:
        return (None, "flat") if cur_avg == 0 else (None, "up")

    trend_pct = (cur_avg - prev_avg) / prev_avg
    if abs(trend_pct) < _CHECKUP_FLAT_THRESHOLD:
        direction = "flat"
    elif trend_pct > 0:
        direction = "up"
    else:
        direction = "down"
    return trend_pct, direction


async def get_nutrient_checkup_aggregates(
    user_id: str, end_date: date
) -> dict[str, dict[str, float | str | None]]:
    """Compute rolling 7-day nutrient averages + trend vs the prior 7 days.

    Protein and Fiber are averaged from `meal_log`'s top-level columns; Sugar
    and the configured vitamins/minerals are averaged from
    `meal_log.entities[].nutrients` (see `nutrient_checkup.micronutrients` in
    tunables.yaml). Used by the build_nutrient_checkup cron.

    Args:
        user_id: Supabase Auth UUID.
        end_date: Last day (inclusive) of the current 7-day window.

    Returns:
        Dict keyed by display nutrient name (e.g. "Protein", "Vitamin C") ->
        {avg, prev_avg, unit, trend_pct, direction}. avg/prev_avg are daily
        averages (sum over 7 days / 7); trend_pct is None when the prior
        week has no data.
    """
    cur_from = end_date - timedelta(days=6)
    prev_to = cur_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=6)

    cur_macros = await get_macros_for_range(user_id, cur_from, end_date)
    prev_macros = await get_macros_for_range(user_id, prev_from, prev_to)

    usda_names = [m.usda_name for m in _CHECKUP_MICRONUTRIENTS.values()]
    cur_micro = await get_micronutrients_for_range(
        user_id, cur_from, end_date, usda_names
    )
    prev_micro = await get_micronutrients_for_range(
        user_id, prev_from, prev_to, usda_names
    )

    result: dict[str, dict[str, float | str | None]] = {}

    for display_name, (field, unit) in _CHECKUP_MACROS.items():
        cur_avg = cur_macros[field] / 7
        prev_avg = prev_macros[field] / 7
        trend_pct, direction = _trend(cur_avg, prev_avg)
        rda = _CHECKUP_RDA[display_name]
        rda_pct = (cur_avg / rda) * 100 if rda else None
        result[display_name] = {
            "avg": cur_avg,
            "prev_avg": prev_avg,
            "unit": unit,
            "trend_pct": trend_pct,
            "direction": direction,
            "rda_pct": rda_pct,
        }

    for display_name, micro_cfg in _CHECKUP_MICRONUTRIENTS.items():
        cur_entry = cur_micro.get(micro_cfg.usda_name)
        prev_entry = prev_micro.get(micro_cfg.usda_name)
        cur_avg = float(cur_entry["amount"]) / 7 if cur_entry else 0.0
        prev_avg = float(prev_entry["amount"]) / 7 if prev_entry else 0.0
        entry_with_unit = cur_entry or prev_entry
        unit = str(entry_with_unit["unit"]) if entry_with_unit else micro_cfg.unit
        trend_pct, direction = _trend(cur_avg, prev_avg)
        rda = _CHECKUP_RDA[display_name]
        rda_pct = (cur_avg / rda) * 100 if rda else None
        result[display_name] = {
            "avg": cur_avg,
            "prev_avg": prev_avg,
            "unit": unit,
            "trend_pct": trend_pct,
            "direction": direction,
            "rda_pct": rda_pct,
        }

    return result


_NOTABLE_UNDER_THRESHOLD = 70.0
_NOTABLE_OVER_THRESHOLD = 150.0

_NUTRIENT_FOOD_HINTS: dict[str, str] = {
    "Protein": "lean meat, eggs, beans, or dairy",
    "Fiber": "whole grains, legumes, or vegetables",
    "Vitamin C": "citrus fruits, berries, or peppers",
    "Vitamin D": "fatty fish, eggs, or fortified foods",
    "Iron": "red meat, spinach, or legumes",
    "Calcium": "dairy, leafy greens, or fortified plant milk",
    "Vitamin B-12": "meat, fish, eggs, or dairy",
}


def _phrase_for(item: dict[str, float | str]) -> str:
    """Return the "why" clause for a single notable nutrient."""
    if item["status"] == "over":
        return "you're well above the daily target"
    hint = _NUTRIENT_FOOD_HINTS.get(str(item["name"]))
    if hint:
        return f"consider eating more {hint}"
    return "consider eating more of this nutrient"


def _combined_phrase(items: list[dict[str, float | str]]) -> str:
    """Return the "why" clause for two notable nutrients."""
    statuses = {item["status"] for item in items}
    if statuses == {"under"}:
        hints = [
            _NUTRIENT_FOOD_HINTS[str(item["name"])]
            for item in items
            if str(item["name"]) in _NUTRIENT_FOOD_HINTS
        ]
        if hints:
            return "consider eating more " + " and ".join(hints)
        return "consider eating more of these nutrients"
    if statuses == {"over"}:
        return "you're well above the daily targets for these"
    return "let's bring these closer to your daily targets"


def summarize_nutrient_checkup(
    nutrients: dict[str, dict[str, float | str | None]],
) -> tuple[list[dict[str, float | str]], str | None]:
    """Build a one-line summary of nutrients notably off their RDA targets.

    A nutrient is "notable" if its `rda_pct` is below
    `_NOTABLE_UNDER_THRESHOLD` (under-target) or above
    `_NOTABLE_OVER_THRESHOLD` (over-target). The top 2 notable nutrients,
    ranked by distance from 100%, drive a deterministic template summary.

    Args:
        nutrients: Output of `get_nutrient_checkup_aggregates`, keyed by
            display name, each with an `rda_pct` (float or None).

    Returns:
        A tuple of (notable nutrients, summary text). `notable` is a list of
        dicts with `name`, `rda_pct`, and `status` ("under" or "over").
        `summary_text` is None when nothing is notable.
    """
    notable: list[dict[str, float | str]] = []
    for name, values in nutrients.items():
        rda_pct = values["rda_pct"]
        if rda_pct is None:
            continue
        rda_pct = float(rda_pct)
        if rda_pct < _NOTABLE_UNDER_THRESHOLD:
            notable.append({"name": name, "rda_pct": rda_pct, "status": "under"})
        elif rda_pct > _NOTABLE_OVER_THRESHOLD:
            notable.append({"name": name, "rda_pct": rda_pct, "status": "over"})

    if not notable:
        return [], None

    notable.sort(key=lambda item: abs(float(item["rda_pct"]) - 100.0), reverse=True)
    top = notable[:2]

    if len(top) == 1:
        item = top[0]
        summary_text = (
            f"This week, your {item['name']} intake is at "
            f"{item['rda_pct']:.0f}% of the daily target — {_phrase_for(item)}."
        )
    else:
        first, second = top
        phrase = _combined_phrase(top)
        summary_text = (
            f"This week: {first['name']} is at {first['rda_pct']:.0f}% and "
            f"{second['name']} is at {second['rda_pct']:.0f}% of their daily "
            f"targets — {phrase}."
        )

    return top, summary_text


async def get_food_breakdown_for_range(
    user_id: str, date_from: date, date_to: date
) -> dict[str, list[dict]]:
    """Summarize logged foods over a range for food-content reasoning.

    Unnests `meal_log.entities` to find the most frequently logged foods
    and the highest-calorie individual items, and cross-references
    `meal_log.flags.junk_items` to find flagged junk foods.

    Args:
        user_id: Supabase Auth UUID.
        date_from: Start of the range (inclusive).
        date_to: End of the range (inclusive).

    Returns:
        Dict with:
            top_foods_by_frequency: list of {food_name, count, total_kcal},
                up to 8 items, ordered by count desc.
            flagged_junk_foods: list of {food_name, count}, foods that
                appeared in flags.junk_items, ordered by count desc.
            highest_calorie_foods: list of {food_name, kcal}, top 5
                individual items by per-item kcal.
    """
    params = {
        "user_id": user_id,
        "date_from": date_from,
        "date_to": date_to,
        **sql_day_params(),
    }

    async with get_session()() as session:
        freq_result = await session.execute(
            sa_text(
                "SELECT "
                "item->>'food_name' AS food_name, "
                "COUNT(*) AS count, "
                "COALESCE(SUM((item->>'kcal')::float), 0) AS total_kcal "
                "FROM meal_log, "
                "jsonb_array_elements(entities) AS item "
                "WHERE user_id = :user_id "
                "AND " + NUTRITION_DATE_SQL + " BETWEEN :date_from AND :date_to "
                "AND deleted_at IS NULL "
                "GROUP BY item->>'food_name' "
                "ORDER BY count DESC "
                "LIMIT 8"
            ),
            params,
        )
        top_foods_by_frequency = [
            {
                "food_name": row.food_name,
                "count": int(row.count),
                "total_kcal": float(row.total_kcal),
            }
            for row in freq_result
        ]

        junk_result = await session.execute(
            sa_text(
                "SELECT "
                "junk_item AS food_name, "
                "COUNT(*) AS count "
                "FROM meal_log, "
                "jsonb_array_elements_text(flags->'junk_items') AS junk_item "
                "WHERE user_id = :user_id "
                "AND " + NUTRITION_DATE_SQL + " BETWEEN :date_from AND :date_to "
                "AND deleted_at IS NULL "
                "AND (flags->>'has_junk')::boolean IS TRUE "
                "GROUP BY junk_item "
                "ORDER BY count DESC"
            ),
            params,
        )
        flagged_junk_foods = [
            {"food_name": row.food_name, "count": int(row.count)} for row in junk_result
        ]

        high_kcal_result = await session.execute(
            sa_text(
                "SELECT "
                "item->>'food_name' AS food_name, "
                "(item->>'kcal')::float AS kcal "
                "FROM meal_log, "
                "jsonb_array_elements(entities) AS item "
                "WHERE user_id = :user_id "
                "AND " + NUTRITION_DATE_SQL + " BETWEEN :date_from AND :date_to "
                "AND deleted_at IS NULL "
                "AND item->>'kcal' IS NOT NULL "
                "ORDER BY kcal DESC "
                "LIMIT 5"
            ),
            params,
        )
        highest_calorie_foods = [
            {"food_name": row.food_name, "kcal": float(row.kcal)}
            for row in high_kcal_result
        ]

    return {
        "top_foods_by_frequency": top_foods_by_frequency,
        "flagged_junk_foods": flagged_junk_foods,
        "highest_calorie_foods": highest_calorie_foods,
    }


async def get_staple_foods(
    user_id: str, days: int | None = None, min_count: int | None = None
) -> dict[str, list[str]]:
    """Foods the user logs repeatedly, grouped by meal type.

    Derived from ``meal_log`` on every call (nothing is stored), so it is
    always consistent with the log. One aggregate query, bounded output:
    at most ``_STAPLES_PER_MEAL_TYPE`` foods per meal type.

    Args:
        user_id: Supabase Auth UUID.
        days: Look-back window ending today; defaults to
            ``memory.staples_window_days``.
        min_count: Minimum number of distinct meals a food must appear in;
            defaults to ``memory.staples_min_count``.

    Returns:
        Meal type -> food names, most frequent first. Meal types with no
        staple are absent. Breakfast, lunch, dinner, snack come first.
    """
    window = days if days is not None else _STAPLES_WINDOW_DAYS
    today = nutrition_today()
    params = {
        "user_id": user_id,
        "date_from": today - timedelta(days=window - 1),
        "date_to": today,
        "min_count": min_count if min_count is not None else _STAPLES_MIN_COUNT,
        "per_meal": _STAPLES_PER_MEAL_TYPE,
        **sql_day_params(),
    }
    async with get_session()() as session:
        result = await session.execute(
            sa_text(
                "SELECT meal_type, food_name FROM ("
                "SELECT meal_type, item->>'food_name' AS food_name, "
                "COUNT(DISTINCT meal_id) AS n, "
                "ROW_NUMBER() OVER (PARTITION BY meal_type "
                "ORDER BY COUNT(DISTINCT meal_id) DESC, item->>'food_name') AS rk "
                "FROM meal_log, jsonb_array_elements(entities) AS item "
                "WHERE user_id = :user_id "
                "AND " + NUTRITION_DATE_SQL + " BETWEEN :date_from AND :date_to "
                "AND deleted_at IS NULL "
                "AND item->>'food_name' IS NOT NULL "
                "GROUP BY meal_type, item->>'food_name' "
                "HAVING COUNT(DISTINCT meal_id) >= :min_count"
                ") ranked WHERE rk <= :per_meal ORDER BY meal_type, rk"
            ),
            params,
        )
        by_meal: dict[str, list[str]] = {}
        for row in result:
            by_meal.setdefault(row.meal_type, []).append(
                row.food_name[:_STAPLE_NAME_MAX_CHARS]
            )

    ordered = {m: by_meal[m] for m in _STAPLE_MEAL_ORDER if m in by_meal}
    ordered.update({m: foods for m, foods in by_meal.items() if m not in ordered})
    return ordered


async def get_history(
    user_id: str,
    query_embedding: list[float] | None = None,
    meal_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    top_k: int = 3,
) -> list[dict]:
    """Hybrid retrieval of past meals: pgvector ANN + SQL filters.

    When `query_embedding` is given, results are ordered by cosine
    similarity to it. Otherwise falls back to pure recency ordering
    (PRD §10.2: "Falls back to pure SQL if no semantic query provided").

    Args:
        user_id: Supabase Auth UUID.
        query_embedding: Optional 768-dim embedding of a semantic query
            (e.g. "salmon dinner").
        meal_type: Optional filter, e.g. "breakfast".
        date_from: Optional start of date range (inclusive).
        date_to: Optional end of date range (inclusive).
        top_k: Maximum number of meals to return.

    Returns:
        List of dicts with meal_id, logged_at, meal_type, kcal, protein_g,
        carbs_g, fat_g, fiber_g, entities — most relevant/recent first.
    """
    async with get_session()() as session:
        stmt = select(MealLog).where(MealLog.user_id == user_id)

        if meal_type is not None:
            stmt = stmt.where(MealLog.meal_type == meal_type)
        if date_from is not None:
            stmt = stmt.where(MealLog.logged_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(MealLog.logged_at <= date_to)

        if query_embedding is not None:
            stmt = stmt.order_by(MealLog.embedding.cosine_distance(query_embedding))
        else:
            stmt = stmt.order_by(MealLog.logged_at.desc())

        stmt = stmt.limit(top_k)

        rows = (await session.execute(stmt)).scalars().all()

    return [
        {
            "meal_id": row.meal_id,
            "logged_at": row.logged_at,
            "meal_type": row.meal_type,
            "kcal": row.kcal,
            "protein_g": row.protein_g,
            "carbs_g": row.carbs_g,
            "fat_g": row.fat_g,
            "fiber_g": row.fiber_g,
            "entities": row.entities,
        }
        for row in rows
    ]


async def get_category_breakdown(user_id: str, days: int) -> list[dict]:
    """Aggregate logged meals by category over the last `days` days.

    One indexed GROUP BY over `ix_meal_log_user_logged_at` — cheap at
    personal scale, no precomputed rollups (avoids write amplification and
    staleness). Covers both the macro-breakdown and frequency/pattern views:
    average macros per category plus how often each category is logged and
    its share of total calories.

    Args:
        user_id: Supabase Auth UUID.
        days: Trailing window size in days (includes today's partial day).

    Returns:
        One dict per category that has at least one meal in the window,
        ordered by total_kcal desc, each with: meal_type, n_meals,
        days_logged, avg_kcal, avg_protein_g, avg_carbs_g, avg_fat_g,
        avg_fiber_g, total_kcal, share_kcal_pct.
    """
    date_from = nutrition_today() - timedelta(days=days - 1)
    async with get_session()() as session:
        result = await session.execute(
            sa_text(
                "SELECT meal_type, "
                "COUNT(*) AS n_meals, "
                "COUNT(DISTINCT " + NUTRITION_DATE_SQL + ") AS days_logged, "
                "COALESCE(AVG(kcal), 0) AS avg_kcal, "
                "COALESCE(AVG(protein_g), 0) AS avg_protein_g, "
                "COALESCE(AVG(carbs_g), 0) AS avg_carbs_g, "
                "COALESCE(AVG(fat_g), 0) AS avg_fat_g, "
                "COALESCE(AVG(fiber_g), 0) AS avg_fiber_g, "
                "COALESCE(SUM(kcal), 0) AS total_kcal "
                "FROM meal_log "
                "WHERE user_id = :user_id AND " + NUTRITION_DATE_SQL + " >= :date_from "
                "AND deleted_at IS NULL "
                "GROUP BY meal_type ORDER BY total_kcal DESC"
            ),
            {"user_id": user_id, "date_from": date_from, **sql_day_params()},
        )
        rows = result.all()

    grand_total = sum(float(r.total_kcal) for r in rows) or 1.0
    return [
        {
            "meal_type": row.meal_type,
            "n_meals": int(row.n_meals),
            "days_logged": int(row.days_logged),
            "avg_kcal": float(row.avg_kcal),
            "avg_protein_g": float(row.avg_protein_g),
            "avg_carbs_g": float(row.avg_carbs_g),
            "avg_fat_g": float(row.avg_fat_g),
            "avg_fiber_g": float(row.avg_fiber_g),
            "total_kcal": float(row.total_kcal),
            "share_kcal_pct": round(float(row.total_kcal) / grand_total * 100, 1),
        }
        for row in rows
    ]


__all__ = [
    "get_category_breakdown",
    "get_food_breakdown_for_range",
    "get_history",
    "get_macros_for_range",
    "get_micronutrients_for_range",
    "get_nutrient_checkup_aggregates",
    "summarize_nutrient_checkup",
]
