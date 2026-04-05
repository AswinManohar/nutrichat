from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.tools.meals import FoodEntity
from backend.agent.tools.usda import usda_lookup_batch, USDAResult, _confidence

MOCK_FDC_RESPONSE = {
    "foods": [{
        "fdcId": 172187,
        "description": "Egg, whole, cooked, scrambled",
        "foodNutrients": [
            {"nutrientName": "Energy", "value": 149.0, "unitName": "kcal"},
            {"nutrientName": "Protein", "value": 9.99, "unitName": "g"},
            {"nutrientName": "Carbohydrate, by difference", "value": 1.61, "unitName": "g"},
            {"nutrientName": "Total lipid (fat)", "value": 11.2, "unitName": "g"},
            {"nutrientName": "Fiber, total dietary", "value": 0.0, "unitName": "g"},
            {"nutrientName": "Total Sugars", "value": 1.22, "unitName": "g"},
            {"nutrientName": "Fatty acids, total saturated", "value": 3.34, "unitName": "g"},
            {"nutrientName": "Vitamin C, total ascorbic acid", "value": 0.0, "unitName": "mg"},
        ],
    }]
}


def _mock_http_response(data: dict) -> AsyncMock:
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=data)
    mock_resp.raise_for_status = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


@pytest.mark.asyncio
async def test_cache_miss_hits_fdc():
    entity = FoodEntity(food_name="scrambled egg", qty_g=100.0, unit="g")

    with patch("backend.agent.tools.usda._cache_lookup", new_callable=AsyncMock, return_value=None), \
         patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock), \
         patch("aiohttp.ClientSession.get", return_value=_mock_http_response(MOCK_FDC_RESPONSE)):
        results = await usda_lookup_batch([entity])

    assert len(results) == 1
    assert results[0].fdc_id == 172187
    assert results[0].kcal == pytest.approx(149.0)  # 100g → scale=1.0


@pytest.mark.asyncio
async def test_scales_nutrients_to_qty_g():
    entity = FoodEntity(food_name="scrambled egg", qty_g=61.0, unit="piece")

    with patch("backend.agent.tools.usda._cache_lookup", new_callable=AsyncMock, return_value=None), \
         patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock), \
         patch("aiohttp.ClientSession.get", return_value=_mock_http_response(MOCK_FDC_RESPONSE)):
        results = await usda_lookup_batch([entity])

    assert results[0].kcal == pytest.approx(149.0 * 61 / 100, rel=0.01)
    assert results[0].protein_g == pytest.approx(9.99 * 61 / 100, rel=0.01)


@pytest.mark.asyncio
async def test_usda_miss_returns_error_result():
    entity = FoodEntity(food_name="xyzzy_nonexistent_food", qty_g=100.0, unit="g")

    with patch("backend.agent.tools.usda._cache_lookup", new_callable=AsyncMock, return_value=None), \
         patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock), \
         patch("aiohttp.ClientSession.get", return_value=_mock_http_response({"foods": []})):
        results = await usda_lookup_batch([entity])

    assert results[0].fdc_id == -1
    assert results[0].match_confidence == 0.0


@pytest.mark.asyncio
async def test_cache_hit_skips_fdc():
    entity = FoodEntity(food_name="scrambled egg", qty_g=61.0, unit="piece")
    cached = {
        "fdc_id": 172187,
        "food_name": "Egg, whole, cooked, scrambled",
        "nutrients": {
            "Energy": {"amount": 149.0, "unit": "kcal"},
            "Protein": {"amount": 9.99, "unit": "g"},
        },
    }

    with patch("backend.agent.tools.usda._cache_lookup", new_callable=AsyncMock, return_value=cached), \
         patch("aiohttp.ClientSession.get") as mock_get:
        results = await usda_lookup_batch([entity])

    mock_get.assert_not_called()
    assert results[0].fdc_id == 172187
    assert results[0].match_confidence == 0.95


@pytest.mark.asyncio
async def test_batch_parallel_multiple_entities():
    entities = [
        FoodEntity(food_name="scrambled egg", qty_g=61.0, unit="piece"),
        FoodEntity(food_name="toast", qty_g=28.0, unit="slice"),
    ]

    with patch("backend.agent.tools.usda._cache_lookup", new_callable=AsyncMock, return_value=None), \
         patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock), \
         patch("aiohttp.ClientSession.get", return_value=_mock_http_response(MOCK_FDC_RESPONSE)):
        results = await usda_lookup_batch(entities)

    assert len(results) == 2


def test_confidence_exact_match():
    score = _confidence("egg scrambled", "Egg, whole, cooked, scrambled")
    assert score > 0.0


def test_confidence_no_overlap():
    score = _confidence("apple", "broccoli steamed")
    assert score == 0.0
