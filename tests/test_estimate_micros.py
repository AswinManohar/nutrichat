"""Tests for LLM-estimated micronutrients (spec 008 R7).

The card waits only for the macro estimate; micros come from a separate call
scheduled in the background and awaited at log time. FR-004 (fallback),
FR-008 (failure never blocks), FR-009 (no extra call on the card path).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.agent.tools import usda
from backend.agent.tools.usda import (
    _ESTIMATE_MICRO_KEYS,
    MicroEstimate,
    MicroEstimates,
    NutritionEstimate,
    _estimated_micros,
    estimate_nutrition_llm,
)
from backend.nutrients import catalog


def _estimate() -> NutritionEstimate:
    return NutritionEstimate(
        kcal=200.0,
        protein_g=6.0,
        carbs_g=30.0,
        fat_g=5.0,
        fiber_g=2.0,
        sugar_g=4.0,
        sat_fat_g=1.0,
    )


def test_allowed_keys_are_estimable_minus_sugar_and_sat_fat() -> None:
    expected = set(catalog.estimable_keys()) - {"total_sugars", "saturated_fat"}
    assert set(_ESTIMATE_MICRO_KEYS) == expected


def test_estimated_micros_drop_unknown_and_usda_only_keys() -> None:
    entries = [
        MicroEstimate(key="iron", per_100g=1.0),
        MicroEstimate(key="Iron", per_100g=9.0),  # duplicate: first wins
        MicroEstimate(key="arsenic", per_100g=1.0),  # USDA-only
        MicroEstimate(key="unobtainium", per_100g=1.0),
    ]
    assert _estimated_micros(entries) == {"iron": 1.0}


def test_schemas_have_no_optional_micro_fields() -> None:
    """Gemini rejects ~40 optional nullable fields: micros stay a flat list,
    and the macro estimate carries no micros at all (kept fast)."""
    assert MicroEstimates.model_json_schema()["properties"]["micros"]["type"] == (
        "array"
    )
    assert "micros" not in NutritionEstimate.model_fields


async def test_card_estimate_makes_one_call_and_schedules_micros() -> None:
    run = SimpleNamespace(output=_estimate())
    with (
        patch.object(usda, "_estimate_cache_lookup", AsyncMock(return_value=None)),
        patch.object(usda, "_estimate_cache_write", AsyncMock()),
        patch.object(
            usda._estimate_agent, "run", AsyncMock(return_value=run)
        ) as agent_run,
        patch.object(usda, "schedule_micro_estimate") as schedule,
    ):
        result = await estimate_nutrition_llm("rasam", qty_g=200.0)

    assert agent_run.await_count == 1  # the card waits for macros only
    schedule.assert_called_once_with("rasam")
    # sugar / sat fat come from the macro estimate (totals for 200 g)
    assert result.micros["total_sugars"].amount == pytest.approx(4.0)
    assert result.micros["saturated_fat"].amount == pytest.approx(1.0)
    assert result.micros["iron"].source == "unknown"  # not fetched yet


async def test_cache_hit_with_micros_skips_both_calls() -> None:
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
        patch.object(usda, "_estimate_cache_lookup", AsyncMock(return_value=cached)),
        patch.object(usda._estimate_agent, "run", AsyncMock()) as agent_run,
        patch.object(usda, "schedule_micro_estimate") as schedule,
    ):
        result = await estimate_nutrition_llm("rasam", qty_g=200.0)

    agent_run.assert_not_awaited()
    schedule.assert_not_called()
    assert result.kcal == pytest.approx(200.0)
    assert result.micros["iron"].amount == pytest.approx(3.0)


async def test_legacy_cache_row_without_micros_schedules_them() -> None:
    cached = {
        "fdc_id": -1,
        "food_name": "rasam",
        "nutrients": {"kcal": 100.0, "protein_g": 3.0, "carbs_g": 15.0},
    }
    with (
        patch.object(usda, "_estimate_cache_lookup", AsyncMock(return_value=cached)),
        patch.object(usda, "schedule_micro_estimate") as schedule,
    ):
        result = await estimate_nutrition_llm("rasam", qty_g=100.0)
    assert result.kcal == pytest.approx(100.0)
    schedule.assert_called_once_with("rasam")


async def test_agent_failure_returns_miss_with_unknown_micros() -> None:
    with (
        patch.object(usda, "_estimate_cache_lookup", AsyncMock(return_value=None)),
        patch.object(
            usda._estimate_agent,
            "run",
            AsyncMock(side_effect=RuntimeError("provider down")),
        ),
    ):
        result = await estimate_nutrition_llm("rasam", qty_g=100.0)
    assert result.fdc_id == -1
    assert set(result.micros) == set(catalog.stored_keys())
    assert all(v.source == "unknown" for v in result.micros.values())


# -- background micro estimate -------------------------------------------------


async def test_run_micro_estimate_filters_and_caches(monkeypatch) -> None:
    monkeypatch.undo()  # use the real _run_micro_estimate (conftest stubs it)
    out = MicroEstimates(
        micros=[
            MicroEstimate(key="iron", per_100g=1.2),
            MicroEstimate(key="tin", per_100g=3.0),  # USDA-only: dropped
        ]
    )
    merge = AsyncMock()
    run = AsyncMock(return_value=SimpleNamespace(output=out))
    with (
        patch.object(usda._micro_agent, "run", run),
        patch.object(usda, "_estimate_cache_merge_micros", merge),
    ):
        got = await usda._run_micro_estimate("rasam")
    assert got == {"iron": 1.2}
    merge.assert_awaited_once_with("rasam", {"iron": 1.2})


async def test_run_micro_estimate_failure_is_empty(monkeypatch) -> None:
    monkeypatch.undo()
    with patch.object(
        usda._micro_agent, "run", AsyncMock(side_effect=RuntimeError("down"))
    ):
        assert await usda._run_micro_estimate("rasam") == {}


async def test_ensure_awaits_scheduled_task_once() -> None:
    calls = 0

    async def slow(food_name: str) -> dict[str, float]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"iron": 2.0}

    with patch.object(usda, "_run_micro_estimate", slow):
        usda.schedule_micro_estimate("Rasam ")
        usda.schedule_micro_estimate("rasam")  # deduplicated by normalized name
        got = await usda.ensure_micro_estimate("rasam")
    assert got == {"iron": 2.0}
    assert calls == 1


async def test_ensure_runs_now_when_nothing_scheduled() -> None:
    with patch.object(
        usda, "_run_micro_estimate", AsyncMock(return_value={"zinc": 1.0})
    ) as run:
        assert await usda.ensure_micro_estimate("dal") == {"zinc": 1.0}
    run.assert_awaited_once_with("dal")
