"""Tests for per-item micronutrient resolution and the meal summary (spec 008).

Covers FR-002..FR-007, FR-004a, FR-006, FR-013 and the USDA-zero
clarification. Uses the bundled USDA SQLite for the fdc_id path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.nutrients import catalog, resolve
from backend.nutrients.models import MicroValue

BANANA = 173944  # Bananas, raw (SR Legacy): vit C 8.7 mg, D 0, trans 0
CHICKEN = 171477  # roasted breast: vit C 0.0 (USDA zero)
HUMMUS = 321358  # reports only "Sugars, Total" (0.34 g)
WAFFLES = 167516  # Folate, DFE 96 vs Folate, total 63


# -- per_100g_from_usda --------------------------------------------------------


def test_usda_values_map_to_catalogue_keys() -> None:
    raw = {
        "Iron, Fe": {"amount": 1.5, "unit": "mg"},
        "Sugars, Total": {"amount": 4.0, "unit": "g"},
        "Fiber, total dietary": {"amount": 2.0, "unit": "g"},  # column key
        "Unrelated thing": {"amount": 9.0, "unit": "g"},
    }
    got = resolve.per_100g_from_usda(raw, estimates={})
    assert got["iron"] == (1.5, "usda")
    assert got["total_sugars"] == (4.0, "usda")
    assert "fiber" not in got
    assert "Unrelated thing" not in got


def test_first_alias_wins_for_folate() -> None:
    raw = {
        "Folate, total": {"amount": 63.0, "unit": "ug"},
        "Folate, DFE": {"amount": 96.0, "unit": "ug"},
    }
    assert resolve.per_100g_from_usda(raw, estimates={})["folate"] == (96.0, "usda")


def test_estimates_fill_only_gaps_and_never_usda_only() -> None:
    raw = {"Iron, Fe": {"amount": 1.0, "unit": "mg"}}
    got = resolve.per_100g_from_usda(
        raw, estimates={"iron": 9.0, "added_sugars": 2.0, "arsenic": 5.0}
    )
    assert got["iron"] == (1.0, "usda")  # USDA wins
    assert got["added_sugars"] == (2.0, "estimated")
    assert "arsenic" not in got  # FR-004a


# -- build_item_micros ----------------------------------------------------------


def test_build_covers_every_stored_key_and_scales() -> None:
    micros = resolve.build_item_micros({"iron": (2.0, "usda")}, qty_g=150)
    assert set(micros) == set(catalog.stored_keys())
    assert micros["iron"] == MicroValue(amount=3.0, source="usda")
    assert micros["sodium"] == MicroValue(amount=None, source="unknown")


def test_usda_zero_is_kept() -> None:
    micros = resolve.build_item_micros({"vitamin_c": (0.0, "usda")}, qty_g=100)
    assert micros["vitamin_c"] == MicroValue(amount=0.0, source="usda")


def test_implausible_estimate_is_rejected() -> None:
    rejected: list[str] = []
    micros = resolve.build_item_micros(
        {"iron": (5000.0, "estimated")}, qty_g=100, rejected=rejected
    )
    assert micros["iron"].source == "unknown"
    assert rejected == ["iron"]


def test_added_sugars_never_exceed_total_sugars() -> None:
    micros = resolve.build_item_micros(
        {"total_sugars": (5.0, "usda"), "added_sugars": (8.0, "estimated")},
        qty_g=100,
    )
    assert micros["added_sugars"].source == "unknown"


def test_usda_only_estimate_is_dropped() -> None:
    micros = resolve.build_item_micros({"tin": (1.0, "estimated")}, qty_g=100)
    assert micros["tin"].source == "unknown"


# -- summarise ------------------------------------------------------------------


def test_summarise_totals_est_known_and_omits_unknown() -> None:
    a = resolve.build_item_micros(
        {"iron": (1.0, "usda"), "biotin": (2.0, "estimated")}, qty_g=100
    )
    b = resolve.build_item_micros({"iron": (3.0, "estimated")}, qty_g=100)
    summary = resolve.summarise([a, b])
    assert summary["iron"] == {"total": 4.0, "est": 3.0, "known": 2}
    assert summary["biotin"] == {"total": 2.0, "est": 2.0, "known": 1}
    assert "sodium" not in summary  # unknown everywhere -> absent
    assert "fiber" not in summary and "salt" not in summary
    for v in summary.values():
        assert 0 <= v["est"] <= v["total"]


def test_summarise_empty() -> None:
    assert resolve.summarise([]) == {}


# -- resolve_micros (server-side derivation) -----------------------------------


async def test_resolve_from_bundled_usda() -> None:
    micros = await resolve.resolve_micros(BANANA, "Bananas, raw", 200)
    assert micros["vitamin_c"] == MicroValue(amount=17.4, source="usda")
    assert micros["vitamin_d"] == MicroValue(amount=0.0, source="usda")


async def test_resolve_usda_zero_for_chicken() -> None:
    micros = await resolve.resolve_micros(CHICKEN, "chicken breast", 100)
    assert micros["vitamin_c"] == MicroValue(amount=0.0, source="usda")


async def test_resolve_sugars_total_alias() -> None:
    micros = await resolve.resolve_micros(HUMMUS, "hummus", 100)
    assert micros["total_sugars"] == MicroValue(amount=0.34, source="usda")


async def test_resolve_estimate_uses_cache_by_name() -> None:
    cached = {
        "fdc_id": -1,
        "food_name": "rasam",
        "nutrients": {
            "kcal": 40.0,
            "sugar_g": 1.0,
            "sat_fat_g": 0.2,
            "micros": {"iron": 0.8, "sodium": 300.0, "arsenic": 1.0},
        },
    }
    with patch.object(
        resolve, "_estimate_cache_lookup", AsyncMock(return_value=cached)
    ):
        micros = await resolve.resolve_micros(-1, "rasam", 200)
    assert micros["iron"] == MicroValue(amount=1.6, source="estimated")
    assert micros["sodium"] == MicroValue(amount=600.0, source="estimated")
    assert micros["total_sugars"] == MicroValue(amount=2.0, source="estimated")
    assert micros["saturated_fat"] == MicroValue(amount=0.4, source="estimated")
    assert micros["arsenic"].source == "unknown"


async def test_resolve_estimate_cache_miss_is_all_unknown() -> None:
    with patch.object(resolve, "_estimate_cache_lookup", AsyncMock(return_value=None)):
        micros = await resolve.resolve_micros(-1, "mystery stew", 100)
    assert all(v.source == "unknown" for v in micros.values())


@pytest.mark.parametrize("qty", [50.0, 100.0, 250.0])
async def test_resolve_scales_linearly(qty: float) -> None:
    micros = await resolve.resolve_micros(BANANA, "Bananas, raw", qty)
    assert micros["iron"].amount == pytest.approx(0.26 * qty / 100)
