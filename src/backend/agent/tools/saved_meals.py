"""Saved-meal ("My Meals") lookup + rebuild helpers for the meal graph.

Kept in the tool layer (not the API) so the LangGraph nodes can import it
without depending on the FastAPI router.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.agent.tools.decompose import normalize_meal_name
from backend.db.models import UserMeal
from backend.db.session import get_session

logger = logging.getLogger(__name__)

# USDAResult fields needed to rebuild a card row from a stored ingredient.
_MACROS = ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sat_fat_g")


def _contiguous_sublist(haystack: list[str], needle: list[str]) -> bool:
    """True if `needle` appears as a contiguous run of tokens in `haystack`."""
    n = len(needle)
    if n == 0 or n > len(haystack):
        return False
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def _best_saved_match(text: str, meals: Sequence[UserMeal]) -> UserMeal | None:
    """Pick the saved meal whose name is the longest contiguous phrase in `text`.

    A saved meal matches when its normalized name tokens appear as a contiguous
    run inside the normalized message tokens, so "chicken biryani" hits inside
    "I had chicken biryani for lunch". The longest (most specific) match wins —
    "fried rice" beats "rice". `meals` must be ordered most-recent-first so ties
    on phrase length resolve to the most recently created meal.

    Returns None when no saved name appears in the message.
    """
    msg_tokens = normalize_meal_name(text).split()
    if not msg_tokens:
        return None
    best: UserMeal | None = None
    best_len = 0
    for meal in meals:
        name_tokens = meal.name_normalized.split()
        if len(name_tokens) > best_len and _contiguous_sublist(msg_tokens, name_tokens):
            best, best_len = meal, len(name_tokens)
    return best


async def find_saved_meal(user_id: str, text: str) -> UserMeal | None:
    """Return the user's saved meal whose name appears as a phrase in `text`.

    Contiguous-phrase match (V1): matches a saved name embedded in a sentence,
    longest match wins. Returns None on no match, empty text, or DB error (so a
    lookup failure degrades to the normal extract->USDA path, never blocking).
    """
    if not normalize_meal_name(text):
        return None
    try:
        async with get_session()() as session:
            result = await session.execute(
                select(UserMeal)
                .where(
                    UserMeal.user_id == user_id,
                    UserMeal.deleted_at.is_(None),
                )
                .order_by(UserMeal.created_at.desc())
            )
            meals = result.scalars().all()
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Saved-meal lookup failed for %s: %s", user_id, exc)
        return None
    return _best_saved_match(text, meals)


def _stored_macro(ing: dict, macro: str) -> float | None:
    """Read one saved macro; unknown (null / listed unknown) stays None."""
    if macro != "kcal" and (
        macro in (ing.get("unknown_nutrients") or ()) or ing.get(macro, 0.0) is None
    ):
        return None
    return float(ing.get(macro, 0.0))


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
                **{m: _stored_macro(ing, m) for m in _MACROS},
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
