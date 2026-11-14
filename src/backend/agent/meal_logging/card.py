"""Confirmation-card shaping for the meal-logging flow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.agent.food.usda import NULLABLE_MACROS
from backend.safety.meal_check import check_meal_for


def serialize_items(usda_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape raw USDA lookup results into the confirmation-card item format.

    Shared by the normal paused meal-logging response and the
    `GET /meals/pending` recovery path so the two shapes can never drift.

    Args:
        usda_results: Raw entries from graph state, keyed by food_name,
            qty_g, match_confidence, kcal, protein_g, carbs_g, fat_g,
            fiber_g, fdc_id, and optional extras.

    Returns:
        List of dicts shaped for the frontend confirmation card.
    """
    items = []
    for r in usda_results:
        # Released clients parse protein/carbs/fat/fiber as required numbers, so
        # an unknown (None) goes out as 0.0 *and* is named in
        # `unknown_nutrients` (the source of truth for "not reported by FDC").
        # sugar_g / sat_fat_g are optional on every client and stay null.
        unknown = [m for m in NULLABLE_MACROS if r.get(m) is None and m in r]
        items.append(
            {
                "food_name": r["food_name"],
                "qty_g": r["qty_g"],
                "confidence": r["match_confidence"],
                "kcal": r["kcal"],
                "protein_g": r["protein_g"] if r["protein_g"] is not None else 0.0,
                "carbs_g": r["carbs_g"] if r["carbs_g"] is not None else 0.0,
                "fat_g": r["fat_g"] if r["fat_g"] is not None else 0.0,
                "fiber_g": r["fiber_g"] if r["fiber_g"] is not None else 0.0,
                "fdc_id": r["fdc_id"],
                "candidates": r.get("candidates", []),
                "candidate_details": r.get("candidate_details", []),
                "source": r.get("source", "USDA"),
                "estimated": r.get("estimated", False),
                "source_dish": r.get("source_dish"),
                "is_composite": r.get("is_composite", False),
                # Spec 003 research R9: the user's original words, when not
                # already derivable from food_name (picker prefill).
                "input_phrase": r.get("input_phrase"),
                # Full breakdown so "Save to My Meals" preserves micros.
                "sugar_g": r.get("sugar_g"),
                "sat_fat_g": r.get("sat_fat_g"),
                "unknown_nutrients": unknown,
                "nutrients": r.get("nutrients", {}),
            }
        )
    return items


def saved_meal_payload(values: dict[str, Any]) -> dict[str, str] | None:
    """Build the `saved_meal` response field from graph state values.

    Uses `.get()` so threads checkpointed before the field existed read as
    "not from a saved meal".

    Returns:
        `{"id", "name", "updated_at"}` when the card came from a saved meal,
        else None.
    """
    saved_id = values.get("saved_meal_id")
    if not saved_id:
        return None
    return {
        "id": saved_id,
        "name": values.get("saved_meal_name") or "",
        "updated_at": values.get("saved_meal_updated_at") or "",
    }


async def card_fields(
    user_id: str, values: Mapping[str, Any], message: str
) -> dict[str, Any]:
    """Message, items, saved-meal link and profile check of a paused card.

    The check (safety/meal_check.py) runs on every card build, so a card
    recovered later reflects the profile as it is now. Its reminders are
    also added to the message, for clients that only show text. Costs one
    profile read, plus today's meals when the patient has a nutrient limit.
    """
    usda_results = values.get("usda_results", [])
    check = await check_meal_for(user_id, usda_results)
    return {
        "message": f"{message}\n\n{check.text}" if check.warnings else message,
        "items": serialize_items(usda_results),
        "saved_meal": saved_meal_payload(values),
        "safety": check.model_dump(),
    }
