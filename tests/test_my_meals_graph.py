"""Routing + rebuild tests for the My Meals graph integration."""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.graph import (
    _route_after_saved_lookup,
    _route_input,
    _route_response,
)
from backend.agent.tools.saved_meals import saved_meal_to_results


def test_route_input_text_goes_to_saved_lookup() -> None:
    assert _route_input({"image_b64": ""}) == "saved_lookup"
    assert _route_input({"image_b64": "base64..."}) == "classify"


def test_route_after_saved_lookup() -> None:
    assert _route_after_saved_lookup({"from_saved": True}) == "present"
    assert _route_after_saved_lookup({"from_saved": False}) == "extract"
    assert _route_after_saved_lookup({}) == "extract"


def test_route_response_decompose_takes_priority() -> None:
    # action=decompose routes to the decompose branch regardless of message text.
    state = {"action": "decompose", "messages": []}
    assert _route_response(state) == "decompose"


def test_saved_meal_to_results_rebuilds_state() -> None:
    meal = SimpleNamespace(
        ingredients=[
            {
                "food_name": "basmati rice cooked",
                "qty_g": 150,
                "kcal": 195,
                "protein_g": 4,
                "carbs_g": 44,
                "fat_g": 0.4,
                "fiber_g": 1.2,
                "fdc_id": 123,
                "nutrients": {"Sodium, Na": {"amount": 1.0, "unit": "mg"}},
            }
        ]
    )
    usda_results, entities = saved_meal_to_results(meal)
    assert len(usda_results) == 1 and len(entities) == 1
    r = usda_results[0]
    assert r["food_name"] == "basmati rice cooked"
    assert r["qty_g"] == 150 and r["kcal"] == 195 and r["fdc_id"] == 123
    assert r["match_confidence"] == 1.0 and r["source"] == "USDA"
    assert "Sodium, Na" in r["nutrients"]
    # entities are the FoodEntity-shaped subset for correction re-resolution
    assert entities[0] == {
        "food_name": "basmati rice cooked",
        "qty_g": 150,
        "unit": "g",
        "confidence": 1.0,
    }
