"""Saved-meal ("My Meals") lookup + rebuild helpers for the meal graph.

Kept in the tool layer (not the API) so the LangGraph nodes can import it
without depending on the FastAPI router.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.agent.tools.decompose import normalize_meal_name
from backend.db.models import UserMeal
from backend.db.session import get_session

# USDAResult fields needed to rebuild a card row from a stored ingredient.
_MACROS = ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sat_fat_g")


async def find_saved_meal(user_id: str, text: str) -> UserMeal | None:
    """Return the user's saved meal whose normalized name matches `text`.

    Normalized-exact match (V1). Returns None on no match or empty text.
    """
    normalized = normalize_meal_name(text)
    if not normalized:
        return None
    async with get_session()() as session:
        result = await session.execute(
            select(UserMeal).where(
                UserMeal.user_id == user_id,
                UserMeal.name_normalized == normalized,
                UserMeal.deleted_at.is_(None),
            )
        )
        return result.scalars().first()


def saved_meal_to_results(meal: UserMeal) -> tuple[list[dict], list[dict]]:
    """Rebuild (usda_results, entities) graph state from a saved meal.

    `usda_results` carries the saved values verbatim (so a straight confirm
    logs exactly what was saved); `entities` is the FoodEntity-shaped subset
    so a correction can still re-resolve through the normal pipeline.
    """
    usda_results: list[dict] = []
    entities: list[dict] = []
    for ing in meal.ingredients:
        usda_results.append(
            {
                "fdc_id": int(ing.get("fdc_id", -1)),
                "food_name": ing["food_name"],
                "qty_g": float(ing["qty_g"]),
                "match_confidence": float(ing.get("match_confidence", 1.0)),
                "candidates": ing.get("candidates", []),
                **{m: float(ing.get(m, 0.0)) for m in _MACROS},
                "nutrients": ing.get("nutrients", {}),
                "source": ing.get("source", "USDA"),
                "estimated": bool(ing.get("estimated", False)),
            }
        )
        entities.append(
            {
                "food_name": ing["food_name"],
                "qty_g": float(ing["qty_g"]),
                "unit": ing.get("unit", "g"),
                "confidence": 1.0,
            }
        )
    return usda_results, entities


__all__ = ["find_saved_meal", "saved_meal_to_results"]
