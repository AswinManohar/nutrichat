from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy import text as sa_text

from backend.db.models import MealLog
from backend.db.session import get_session


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
                "AND logged_at::date BETWEEN :date_from AND :date_to"
            ),
            {"user_id": user_id, "date_from": date_from, "date_to": date_to},
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
                    "AND logged_at::date BETWEEN :date_from AND :date_to "
                    "AND item->'nutrients' ? :nutrient"
                ),
                {
                    "user_id": user_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "nutrient": nutrient,
                },
            )
            row = result.one()
            if row.total is not None:
                results[nutrient] = {"amount": float(row.total), "unit": row.unit}

    return results


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
    params = {"user_id": user_id, "date_from": date_from, "date_to": date_to}

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
                "AND logged_at::date BETWEEN :date_from AND :date_to "
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
                "AND logged_at::date BETWEEN :date_from AND :date_to "
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
                "AND logged_at::date BETWEEN :date_from AND :date_to "
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


__all__ = [
    "get_food_breakdown_for_range",
    "get_history",
    "get_macros_for_range",
    "get_micronutrients_for_range",
]
