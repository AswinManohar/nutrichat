"""usda_batch_node propagates per-entity source_dish onto usda_results."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.agent.graph import usda_batch_node
from backend.agent.tools.usda import USDAResult


def _result(food_name: str) -> USDAResult:
    return USDAResult(
        fdc_id=1,
        food_name=food_name,
        qty_g=100,
        kcal=100,
        protein_g=1,
        carbs_g=1,
        fat_g=1,
        fiber_g=1,
        sugar_g=0,
        sat_fat_g=0,
        nutrients={},
        candidates=[],
        match_confidence=1.0,
    )


async def test_source_dish_propagated_onto_results() -> None:
    state = {
        "entities": [
            {"food_name": "basmati rice", "qty_g": 150, "unit": "g",
             "confidence": 1.0, "is_composite": False,
             "source_dish": "chicken biryani"},
            {"food_name": "apple", "qty_g": 150, "unit": "g",
             "confidence": 1.0, "is_composite": False, "source_dish": None},
        ]
    }
    fake = AsyncMock(return_value=[_result("rice white cooked"), _result("apple raw")])
    with patch("backend.agent.graph.usda_lookup_batch", fake):
        out = await usda_batch_node(state)

    results = out["usda_results"]
    assert results[0]["source_dish"] == "chicken biryani"
    assert results[1]["source_dish"] is None
