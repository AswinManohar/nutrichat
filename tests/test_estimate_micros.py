"""Tests for micronutrients from the single LLM estimate call (spec 008 R7).

FR-004 (fallback), FR-007 (caps via build_item_micros), FR-008 (failure never
blocks), FR-009 (one call per food).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.agent.tools.usda import (
    EstimatedMicros,
    NutritionEstimate,
    estimate_nutrition_llm,
)
from backend.nutrients import catalog


def _estimate(**micros: float) -> NutritionEstimate:
    return NutritionEstimate(
        kcal=200.0,
        protein_g=6.0,
        carbs_g=30.0,
        fat_g=5.0,
        fiber_g=2.0,
        sugar_g=4.0,
        sat_fat_g=1.0,
        micros=EstimatedMicros(**micros),
    )


def test_estimated_micros_cover_estimable_keys_except_sugar_and_sat_fat() -> None:
    expected = set(catalog.estimable_keys()) - {"total_sugars", "saturated_fat"}
    assert set(EstimatedMicros.model_fields) == expected


def test_estimated_micros_reject_unknown_fields() -> None:
    with pytest.raises(ValueError):
        EstimatedMicros(arsenic=1.0)  # USDA-only, never estimated


async def test_estimate_populates_scaled_micros_and_caches_per_100g() -> None:
    run = SimpleNamespace(output=_estimate(iron=1.5, sodium=400.0))
    write = AsyncMock()
    with (
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._estimate_cache_write", write),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
            return_value=run,
        ) as agent_run,
    ):
        result = await estimate_nutrition_llm("rasam", qty_g=200.0)

    assert agent_run.await_count == 1  # FR-009: one call
    assert result.micros["iron"].amount == pytest.approx(3.0)
    assert result.micros["iron"].source == "estimated"
    assert result.micros["sodium"].amount == pytest.approx(800.0)
    # sugar / sat fat come from the macro fields (totals for 200 g)
    assert result.micros["total_sugars"].amount == pytest.approx(4.0)
    assert result.micros["saturated_fat"].amount == pytest.approx(1.0)
    assert result.micros["arsenic"].source == "unknown"
    cached = write.await_args.args[1]
    assert cached["micros"] == {"iron": 1.5, "sodium": 400.0}


async def test_cache_hit_returns_same_micros_without_agent_call() -> None:
    cached = {
        "fdc_id": -1,
        "food_name": "rasam",
        "nutrients": {
            "kcal": 100.0,
            "protein_g": 3.0,
            "carbs_g": 15.0,
            "fat_g": 2.5,
            "fiber_g": 1.0,
            "sugar_g": 2.0,
            "sat_fat_g": 0.5,
            "micros": {"iron": 1.5},
        },
    }
    with (
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=cached,
        ),
        patch(
            "backend.agent.tools.usda._estimate_agent.run", new_callable=AsyncMock
        ) as agent_run,
    ):
        result = await estimate_nutrition_llm("rasam", qty_g=200.0)

    agent_run.assert_not_awaited()
    assert result.kcal == pytest.approx(200.0)
    assert result.micros["iron"].amount == pytest.approx(3.0)
    assert result.micros["total_sugars"].amount == pytest.approx(4.0)


async def test_legacy_cache_row_without_micros_still_works() -> None:
    cached = {
        "fdc_id": -1,
        "food_name": "rasam",
        "nutrients": {"kcal": 100.0, "protein_g": 3.0, "carbs_g": 15.0},
    }
    with patch(
        "backend.agent.tools.usda._estimate_cache_lookup",
        new_callable=AsyncMock,
        return_value=cached,
    ):
        result = await estimate_nutrition_llm("rasam", qty_g=100.0)
    assert result.kcal == pytest.approx(100.0)
    assert result.micros["iron"].source == "unknown"


async def test_agent_failure_returns_miss_with_unknown_micros() -> None:
    with (
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("provider down"),
        ),
    ):
        result = await estimate_nutrition_llm("rasam", qty_g=100.0)
    assert result.fdc_id == -1
    assert set(result.micros) == set(catalog.stored_keys())
    assert all(v.source == "unknown" for v in result.micros.values())
