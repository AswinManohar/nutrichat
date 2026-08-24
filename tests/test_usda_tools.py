from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.tools.meals import FoodEntity
from backend.agent.tools.usda import (
    NutritionEstimate,
    _confidence,
    _nutrients_by_name,
    estimate_nutrition_llm,
    usda_lookup_batch,
)
from backend.agent.tools.usda_local import LocalMatch
from backend.config import get_tunables


@pytest.fixture(autouse=True)
def _force_api_path():
    """Most tests in this file exercise the FDC API path (they mock
    aiohttp/_cache_lookup). use_local_db defaults to true, so force the
    dispatch point to route through _fetch_usda_api unless a test
    overrides this."""
    with patch("backend.agent.tools.usda._use_local", return_value=False):
        yield


MOCK_FDC_RESPONSE = {
    "foods": [
        {
            "fdcId": 172187,
            "description": "Egg, whole, cooked, scrambled",
            "foodNutrients": [
                {"nutrientName": "Energy", "value": 149.0, "unitName": "kcal"},
                {"nutrientName": "Protein", "value": 9.99, "unitName": "g"},
                {
                    "nutrientName": "Carbohydrate, by difference",
                    "value": 1.61,
                    "unitName": "g",
                },
                {"nutrientName": "Total lipid (fat)", "value": 11.2, "unitName": "g"},
                {"nutrientName": "Fiber, total dietary", "value": 0.0, "unitName": "g"},
                {"nutrientName": "Total Sugars", "value": 1.22, "unitName": "g"},
                {
                    "nutrientName": "Fatty acids, total saturated",
                    "value": 3.34,
                    "unitName": "g",
                },
                {
                    "nutrientName": "Vitamin C, total ascorbic acid",
                    "value": 0.0,
                    "unitName": "mg",
                },
            ],
        }
    ]
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

    with (
        patch(
            "backend.agent.tools.usda._cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock),
        patch(
            "aiohttp.ClientSession.get",
            return_value=_mock_http_response(MOCK_FDC_RESPONSE),
        ),
    ):
        results = await usda_lookup_batch([entity])

    assert len(results) == 1
    assert results[0].fdc_id == 172187
    assert results[0].kcal == pytest.approx(149.0)  # 100g → scale=1.0


@pytest.mark.asyncio
async def test_scales_nutrients_to_qty_g():
    entity = FoodEntity(food_name="scrambled egg", qty_g=61.0, unit="piece")

    with (
        patch(
            "backend.agent.tools.usda._cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock),
        patch(
            "aiohttp.ClientSession.get",
            return_value=_mock_http_response(MOCK_FDC_RESPONSE),
        ),
    ):
        results = await usda_lookup_batch([entity])

    assert results[0].kcal == pytest.approx(149.0 * 61 / 100, rel=0.01)
    assert results[0].protein_g == pytest.approx(9.99 * 61 / 100, rel=0.01)


@pytest.mark.asyncio
async def test_usda_miss_falls_back_to_estimate_when_llm_succeeds():
    """A true USDA miss (no foods returned) now falls back to an LLM
    estimate (Plan A) rather than being returned as a bare miss."""
    entity = FoodEntity(food_name="xyzzy_nonexistent_food", qty_g=100.0, unit="g")

    fake_run = MagicMock()
    fake_run.output = NutritionEstimate(
        kcal=120.0,
        protein_g=5.0,
        carbs_g=15.0,
        fat_g=3.0,
        fiber_g=1.0,
        sugar_g=1.0,
        sat_fat_g=1.0,
    )

    with (
        patch(
            "backend.agent.tools.usda._cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock),
        patch("backend.agent.tools.usda._estimate_cache_write", new_callable=AsyncMock),
        patch(
            "aiohttp.ClientSession.get", return_value=_mock_http_response({"foods": []})
        ),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
            return_value=fake_run,
        ),
    ):
        results = await usda_lookup_batch([entity])

    assert results[0].fdc_id == -1
    assert results[0].estimated is True
    assert results[0].source == "LLM_ESTIMATE"


@pytest.mark.asyncio
async def test_usda_miss_returns_bare_miss_when_llm_also_fails():
    """If the LLM estimate call itself fails, fall back to a bare miss
    (fdc_id=-1, estimated=False) so the item is excluded from logging."""
    entity = FoodEntity(food_name="xyzzy_nonexistent_food", qty_g=100.0, unit="g")

    with (
        patch(
            "backend.agent.tools.usda._cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock),
        patch(
            "aiohttp.ClientSession.get", return_value=_mock_http_response({"foods": []})
        ),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM unavailable"),
        ),
    ):
        results = await usda_lookup_batch([entity])

    assert results[0].fdc_id == -1
    assert results[0].match_confidence == 0.0
    assert results[0].estimated is False


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

    with (
        patch(
            "backend.agent.tools.usda._cache_lookup",
            new_callable=AsyncMock,
            return_value=cached,
        ),
        patch("aiohttp.ClientSession.get") as mock_get,
    ):
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

    fake_run = MagicMock()
    fake_run.output = _FAKE_ESTIMATE

    with (
        patch(
            "backend.agent.tools.usda._cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock),
        patch("backend.agent.tools.usda._estimate_cache_write", new_callable=AsyncMock),
        patch(
            "aiohttp.ClientSession.get",
            return_value=_mock_http_response(MOCK_FDC_RESPONSE),
        ),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
            return_value=fake_run,
        ),
    ):
        results = await usda_lookup_batch(entities)

    assert len(results) == 2


def test_confidence_exact_match():
    score = _confidence("egg scrambled", "Egg, whole, cooked, scrambled")
    assert score > 0.0


def test_confidence_no_overlap():
    score = _confidence("apple", "broccoli steamed")
    assert score == 0.0


def test_confidence_full_coverage_despite_verbose_description():
    # Every query word is present; FDC's extra descriptors and plurals must
    # NOT drag the score down (the Jaccard regression that over-estimated).
    assert _confidence("banana", "Bananas, raw") == 1.0
    assert _confidence("white rice", "Rice, white, long-grain, raw") == 1.0
    assert (
        _confidence(
            "grilled chicken breast",
            "Chicken, broilers or fryers, breast, meat only, cooked, grilled",
        )
        == 1.0
    )


def test_confidence_partial_match_below_floor():
    # Only "chicken" overlaps with "Chicken spread" -> 1 of 2 words = 0.5,
    # below the 0.6 floor, so this correctly falls through to estimation.
    score = _confidence("chicken biryani", "Chicken spread")
    assert score == 0.5
    assert score < get_tunables().usda.match_confidence_floor


def test_confidence_drops_filler_words():
    # "with" is a stopword; coverage is over {rice, chicken}.
    assert _confidence("rice with chicken", "Rice, white, chicken added") == 1.0


def test_nutrients_by_name_prefers_kcal_over_kj():
    # FDC lists Energy twice; the kJ row must never overwrite kcal,
    # regardless of which order they arrive in.
    kcal_first = [
        {"nutrientName": "Energy", "value": 313.0, "unitName": "KCAL"},
        {"nutrientName": "Energy", "value": 1310.0, "unitName": "kJ"},
        {"nutrientName": "Protein", "value": 13.0, "unitName": "G"},
    ]
    kj_first = list(reversed(kcal_first))

    for payload in (kcal_first, kj_first):
        raw = _nutrients_by_name(payload)
        assert raw["Energy"] == (313.0, "kcal")
        assert raw["Protein"] == (13.0, "g")


def test_energy_falls_back_to_atwater_names():
    # Foundation entries often lack a plain "Energy" row and report kcal
    # under Atwater names instead.
    from backend.agent.tools.usda import _energy_kcal

    raw = {
        "Energy (Atwater General Factors)": (47.0, "kcal"),
        "Protein": (1.0, "g"),
    }
    assert _energy_kcal(raw) == 47.0
    assert _energy_kcal({"Energy": (100.0, "kcal")}) == 100.0
    assert _energy_kcal({"Protein": (1.0, "g")}) == 0.0


# ---------------------------------------------------------------------------
# Plan A — confidence gate + LLM estimation fallback
# ---------------------------------------------------------------------------

# A weak match — "chicken biryani" vs "Chicken spread" shares no words,
# so _confidence() returns 0.0, well below match_confidence_floor (0.5).
WEAK_MATCH_RESPONSE = {
    "foods": [
        {
            "fdcId": 99999,
            "description": "Chicken spread",
            "foodNutrients": [
                {"nutrientName": "Energy", "value": 200.0, "unitName": "kcal"},
                {"nutrientName": "Protein", "value": 10.0, "unitName": "g"},
            ],
        }
    ]
}

_FAKE_ESTIMATE = NutritionEstimate(
    kcal=450.0,
    protein_g=25.0,
    carbs_g=55.0,
    fat_g=12.0,
    fiber_g=3.0,
    sugar_g=2.0,
    sat_fat_g=4.0,
)


@pytest.mark.asyncio
async def test_low_confidence_match_falls_back_to_llm_estimate():
    entity = FoodEntity(food_name="chicken biryani", qty_g=300.0, unit="bowl")

    fake_run = MagicMock()
    fake_run.output = _FAKE_ESTIMATE

    with (
        patch(
            "backend.agent.tools.usda._cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock),
        patch("backend.agent.tools.usda._estimate_cache_write", new_callable=AsyncMock),
        patch(
            "aiohttp.ClientSession.get",
            return_value=_mock_http_response(WEAK_MATCH_RESPONSE),
        ),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
            return_value=fake_run,
        ),
    ):
        results = await usda_lookup_batch([entity])

    assert len(results) == 1
    r = results[0]
    assert r.fdc_id == -1
    assert r.estimated is True
    assert r.source == "LLM_ESTIMATE"
    assert r.food_name == "chicken biryani"
    # 300g of a 450 kcal/300g estimate -> kcal scales with qty_g
    assert r.kcal == pytest.approx(450.0, rel=0.05)


@pytest.mark.asyncio
async def test_no_match_falls_back_to_llm_estimate():
    entity = FoodEntity(food_name="xyzzy_nonexistent_food", qty_g=100.0, unit="g")

    fake_run = MagicMock()
    fake_run.output = _FAKE_ESTIMATE

    with (
        patch(
            "backend.agent.tools.usda._cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock),
        patch("backend.agent.tools.usda._estimate_cache_write", new_callable=AsyncMock),
        patch(
            "aiohttp.ClientSession.get", return_value=_mock_http_response({"foods": []})
        ),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
            return_value=fake_run,
        ),
    ):
        results = await usda_lookup_batch([entity])

    assert results[0].estimated is True
    assert results[0].source == "LLM_ESTIMATE"


@pytest.mark.asyncio
async def test_estimate_uses_cache_when_present():
    cached = {
        "fdc_id": -123,
        "food_name": "chicken biryani",
        "nutrients": {
            "kcal": 150.0,
            "protein_g": 8.0,
            "carbs_g": 18.0,
            "fat_g": 4.0,
            "fiber_g": 1.0,
            "sugar_g": 1.0,
            "sat_fat_g": 1.5,
        },
    }

    with (
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=cached,
        ),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
        ) as mock_run,
    ):
        result = await estimate_nutrition_llm("chicken biryani", qty_g=300.0)

    mock_run.assert_not_called()
    assert result.estimated is True
    assert result.source == "LLM_ESTIMATE"
    # cached per-100g kcal=150 -> 300g => 450
    assert result.kcal == pytest.approx(450.0)


@pytest.mark.asyncio
async def test_high_confidence_match_is_not_overridden():
    entity = FoodEntity(food_name="scrambled egg", qty_g=61.0, unit="piece")

    with (
        patch(
            "backend.agent.tools.usda._cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._cache_write", new_callable=AsyncMock),
        patch(
            "aiohttp.ClientSession.get",
            return_value=_mock_http_response(MOCK_FDC_RESPONSE),
        ),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
        ) as mock_run,
    ):
        results = await usda_lookup_batch([entity])

    mock_run.assert_not_called()
    assert results[0].estimated is False
    assert results[0].source == "USDA"


# ---------------------------------------------------------------------------
# Local SQLite read path
# ---------------------------------------------------------------------------

_LOCAL_MATCH = LocalMatch(
    fdc_id=555,
    description="Chicken, broilers or fryers, breast, meat only, cooked, grilled",
    match_confidence=0.9,
    candidates=["Chicken, broilers or fryers, breast, meat only, cooked, grilled"],
    macros_per_100g={
        "kcal": 165.0,
        "protein_g": 31.0,
        "carbs_g": 0.0,
        "fat_g": 3.6,
        "fiber_g": 0.0,
        "sugar_g": 0.0,
        "sat_fat_g": 1.0,
    },
    nutrients_per_100g={
        "Energy": {"amount": 165.0, "unit": "kcal"},
        "Protein": {"amount": 31.0, "unit": "g"},
    },
)


@pytest.mark.asyncio
async def test_local_path_scales_macros_and_skips_cache_lookup():
    entity = FoodEntity(food_name="grilled chicken breast", qty_g=250.0, unit="g")

    with (
        patch("backend.agent.tools.usda._use_local", return_value=True),
        patch("backend.agent.tools.usda.usda_local.lookup", return_value=_LOCAL_MATCH),
        patch(
            "backend.agent.tools.usda._cache_lookup", new_callable=AsyncMock
        ) as mock_cache_lookup,
    ):
        results = await usda_lookup_batch([entity])

    mock_cache_lookup.assert_not_called()
    assert len(results) == 1
    r = results[0]
    assert r.fdc_id == 555
    assert r.source == "USDA"
    assert r.kcal == pytest.approx(165.0 * 2.5)
    assert r.protein_g == pytest.approx(31.0 * 2.5)
    assert r.fat_g == pytest.approx(3.6 * 2.5)


@pytest.mark.asyncio
async def test_local_path_low_confidence_falls_back_to_llm_estimate():
    entity = FoodEntity(food_name="chicken biryani", qty_g=300.0, unit="bowl")

    weak_match = LocalMatch(
        fdc_id=1,
        description="Chicken spread",
        match_confidence=0.1,
        candidates=["Chicken spread"],
        macros_per_100g={
            "kcal": 200.0,
            "protein_g": 10.0,
            "carbs_g": 0.0,
            "fat_g": 15.0,
            "fiber_g": 0.0,
            "sugar_g": 0.0,
            "sat_fat_g": 3.0,
        },
        nutrients_per_100g={},
    )

    fake_run = MagicMock()
    fake_run.output = _FAKE_ESTIMATE

    with (
        patch("backend.agent.tools.usda._use_local", return_value=True),
        patch("backend.agent.tools.usda.usda_local.lookup", return_value=weak_match),
        patch(
            "backend.agent.tools.usda._cache_lookup", new_callable=AsyncMock
        ) as mock_cache_lookup,
        patch(
            "backend.agent.tools.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.tools.usda._estimate_cache_write", new_callable=AsyncMock),
        patch(
            "backend.agent.tools.usda._estimate_agent.run",
            new_callable=AsyncMock,
            return_value=fake_run,
        ),
    ):
        results = await usda_lookup_batch([entity])

    mock_cache_lookup.assert_not_called()
    assert results[0].fdc_id == -1
    assert results[0].estimated is True
    assert results[0].source == "LLM_ESTIMATE"
