from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.tools.meals import (
    FoodEntity,
    ExtractionResult,
    ImageClassification,
    MealLogResult,
    classify_intent,
    format_confirmation_card,
)
from backend.agent.tools.usda import NutrientValue, USDAResult


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_food_entity_defaults():
    e = FoodEntity(food_name="egg", qty_g=61.0, unit="piece")
    assert e.confidence == 1.0


def test_food_entity_rejects_zero_qty():
    with pytest.raises(Exception):
        FoodEntity(food_name="egg", qty_g=0.0, unit="piece")


def test_food_entity_rejects_extra_fields():
    with pytest.raises(Exception):
        FoodEntity(food_name="egg", qty_g=61.0, unit="piece", unknown_field="x")


def test_usda_result_has_nutrients():
    r = USDAResult(
        fdc_id=1, food_name="egg", qty_g=61.0,
        match_confidence=0.9, candidates=[],
        kcal=87.0, protein_g=6.0, carbs_g=0.6,
        fat_g=6.0, fiber_g=0.0, sugar_g=0.6, sat_fat_g=1.6,
        nutrients={"Vitamin C": NutrientValue(amount=0.0, unit="mg")},
    )
    assert r.nutrients["Vitamin C"].amount == 0.0


def test_image_classification_no_food():
    ic = ImageClassification(
        is_food=False, food_items=[], ingredients=[], reason="No food visible"
    )
    assert not ic.is_food


# ---------------------------------------------------------------------------
# classify_intent tests
# ---------------------------------------------------------------------------


def test_classify_intent_confirm():
    assert classify_intent("yes") == "confirm"
    assert classify_intent("Looks good!") == "confirm"
    assert classify_intent("ok log it") == "confirm"


def test_classify_intent_reject():
    assert classify_intent("no") == "reject"
    assert classify_intent("cancel") == "reject"
    assert classify_intent("never mind") == "reject"


def test_classify_intent_correct():
    assert classify_intent("actually 3 eggs") == "correct"
    assert classify_intent("swap oat milk for almond milk") == "correct"


# ---------------------------------------------------------------------------
# format_confirmation_card tests
# ---------------------------------------------------------------------------


def _make_result(fdc_id: int = 172187, kcal: float = 182.0) -> USDAResult:
    return USDAResult(
        fdc_id=fdc_id, food_name="Egg, scrambled", qty_g=122.0,
        match_confidence=0.9, candidates=["Egg, scrambled", "Egg, fried"],
        kcal=kcal, protein_g=12.0, carbs_g=2.0,
        fat_g=13.0, fiber_g=0.0, sugar_g=1.0, sat_fat_g=3.4,
        nutrients={},
    )


def test_format_card_contains_food_name():
    card = format_confirmation_card([_make_result()])
    assert "Egg, scrambled" in card


def test_format_card_shows_totals():
    card = format_confirmation_card([_make_result(kcal=182.0)])
    assert "Total" in card
    assert "182" in card


def test_format_card_miss_shows_error():
    miss = USDAResult(
        fdc_id=-1, food_name="mystery_food", qty_g=100.0,
        match_confidence=0.0, candidates=[],
        kcal=0.0, protein_g=0.0, carbs_g=0.0, fat_g=0.0,
        fiber_g=0.0, sugar_g=0.0, sat_fat_g=0.0, nutrients={},
    )
    card = format_confirmation_card([miss])
    assert "not found" in card.lower() or "mystery_food" in card


# ---------------------------------------------------------------------------
# log_meal tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_meal_returns_result():
    results = [_make_result(kcal=182.0)]

    with patch("backend.agent.tools.meals._insert_meal_log", new_callable=AsyncMock) as mock_insert, \
         patch("backend.agent.tools.meals.increment_today", new_callable=AsyncMock):
        mock_insert.return_value = "test-meal-uuid"
        from backend.agent.tools.meals import log_meal
        result = await log_meal("user1", results, "breakfast")

    assert result.meal_id == "test-meal-uuid"
    assert result.kcal == pytest.approx(182.0)
    assert result.n_items == 1


@pytest.mark.asyncio
async def test_log_meal_excludes_misses():
    miss = USDAResult(
        fdc_id=-1, food_name="unknown", qty_g=100.0,
        match_confidence=0.0, candidates=[],
        kcal=0.0, protein_g=0.0, carbs_g=0.0, fat_g=0.0,
        fiber_g=0.0, sugar_g=0.0, sat_fat_g=0.0, nutrients={},
    )
    good = _make_result(kcal=182.0)

    with patch("backend.agent.tools.meals._insert_meal_log", new_callable=AsyncMock) as mock_insert, \
         patch("backend.agent.tools.meals.increment_today", new_callable=AsyncMock):
        mock_insert.return_value = "uuid-2"
        from backend.agent.tools.meals import log_meal
        result = await log_meal("user1", [miss, good], "lunch")

    assert result.n_items == 1
    assert result.kcal == pytest.approx(182.0)
