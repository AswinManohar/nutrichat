"""Resolve per-item tracked micronutrients and summarise them per meal.

The single implementation of spec 008's value rule (FR-003..FR-007):

* a USDA value — including 0 — always wins;
* otherwise an AI estimate (pre-computed for USDA foods, from the single
  estimate call for unmatched foods), unless the key is USDA-only;
* estimates above the catalogue's ``max_per_100g`` cap, or added sugars above
  total sugars, are rejected;
* anything else is unknown — never 0.

``resolve_micros`` derives an item's values server-side from its food id (or
its estimate-cache row) so a logged meal never stores client-supplied
nutrition (research R9).
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from backend.agent.tools import usda_local
from backend.config import NutrientDef, get_catalog
from backend.nutrients import catalog
from backend.nutrients.models import MicroValue

logger = logging.getLogger(__name__)

PerHundred = dict[str, tuple[float, str]]  # key -> (per-100 g amount, source)

_UNIT_TO_MCG = {"g": 1_000_000.0, "mg": 1_000.0, "mcg": 1.0, "ug": 1.0, "µg": 1.0}
_ROUND = 4


@lru_cache(maxsize=1)
def _defs() -> dict[str, NutrientDef]:
    """Catalogue entries by key."""
    return {n.key: n for n in get_catalog().nutrients}


def _convert(amount: float, from_unit: str, to_unit: str) -> float | None:
    """Convert between g/mg/mcg; None for units that can't convert (IU, kcal)."""
    src = _UNIT_TO_MCG.get(from_unit.lower())
    dst = _UNIT_TO_MCG.get(to_unit.lower())
    if src is None or dst is None:
        return None
    return amount * src / dst


def per_100g_from_usda(
    nutrients: dict[str, dict], estimates: dict[str, float]
) -> PerHundred:
    """Map a food's USDA nutrients (+ pre-computed estimates) onto catalogue keys.

    Args:
        nutrients: USDA name -> {"amount", "unit"}, per 100 g.
        estimates: Catalogue key -> per-100 g AI estimate for gaps.

    Returns:
        Key -> (per-100 g amount in the catalogue unit, "usda" | "estimated")
        for every stored key that has a value. USDA wins over an estimate;
        USDA-only keys never take an estimate.
    """
    usda_only = catalog.usda_only_keys()
    out: PerHundred = {}
    for key in catalog.stored_keys():
        unit = _defs()[key].unit
        for name in _defs()[key].usda_names:  # priority order: first wins
            raw = nutrients.get(name)
            if not isinstance(raw, dict) or raw.get("amount") is None:
                continue
            value = _convert(float(raw["amount"]), str(raw.get("unit", unit)), unit)
            if value is not None:
                out[key] = (value, "usda")
                break
        if key not in out and key not in usda_only and key in estimates:
            out[key] = (float(estimates[key]), "estimated")
    return out


def per_100g_from_estimate_row(nutrients: dict) -> PerHundred:
    """Read per-100 g micros from an LLM-estimate cache row (``food_source``).

    Total sugars and saturated fat come from the row's ``sugar_g`` /
    ``sat_fat_g`` macros; the rest from its ``micros`` object. Legacy rows
    without ``micros`` yield only those two.
    """
    estimable = set(catalog.estimable_keys())
    out: PerHundred = {
        key: (float(value), "estimated")
        for key, value in (nutrients.get("micros") or {}).items()
        if key in estimable and value is not None
    }
    for macro, key in (("sugar_g", "total_sugars"), ("sat_fat_g", "saturated_fat")):
        if nutrients.get(macro) is not None:
            out[key] = (float(nutrients[macro]), "estimated")
    return out


def build_item_micros(
    per_100g: PerHundred, qty_g: float, rejected: list[str] | None = None
) -> dict[str, MicroValue]:
    """Scale per-100 g values to an item and apply the acceptance rules.

    Args:
        per_100g: Key -> (per-100 g amount, source) from one of the
            ``per_100g_from_*`` helpers.
        qty_g: The item's gram weight.
        rejected: Optional list that collects keys whose estimate was dropped
            (telemetry, FR-011).

    Returns:
        A MicroValue for every stored key; unknown where there is no
        acceptable value.
    """
    usda_only = catalog.usda_only_keys()
    micros: dict[str, MicroValue] = {}
    for key in catalog.stored_keys():
        entry = per_100g.get(key)
        if entry is None:
            micros[key] = MicroValue()
            continue
        value, source = entry
        if source == "estimated":
            cap = _defs()[key].max_per_100g
            if key in usda_only or value < 0 or (cap is not None and value > cap):
                if rejected is not None:
                    rejected.append(key)
                micros[key] = MicroValue()
                continue
        micros[key] = MicroValue(
            amount=round(value * qty_g / 100.0, _ROUND),
            source="usda" if source == "usda" else "estimated",
        )

    added, total = micros.get("added_sugars"), micros.get("total_sugars")
    if (
        added is not None
        and total is not None
        and added.amount is not None
        and total.amount is not None
        and added.amount > total.amount
    ):
        if rejected is not None:
            rejected.append("added_sugars")
        micros["added_sugars"] = MicroValue()
    return micros


def summarise(items: list[dict[str, MicroValue]]) -> dict[str, dict]:
    """Meal-level summary ``{key: {total, est, known}}`` (data-model §3).

    Keys with no known value on any item are omitted (= unknown).
    """
    summary: dict[str, dict] = {}
    for key in catalog.stored_keys():
        total = est = 0.0
        known = 0
        for item in items:
            mv = item.get(key)
            if mv is None or mv.amount is None:
                continue
            total += mv.amount
            known += 1
            if mv.source == "estimated":
                est += mv.amount
        if known:
            summary[key] = {
                "total": round(total, _ROUND),
                "est": round(est, _ROUND),
                "known": known,
            }
    return summary


async def _estimate_cache_lookup(food_name: str) -> dict | None:
    """Look up a cached LLM estimate row by food name.

    Imported inside the function on purpose: ``usda.py`` imports this module
    (``build_item_micros``), so a top-level import would be circular.
    """
    from backend.agent.tools.usda import _estimate_cache_lookup as lookup

    return await lookup(food_name)


async def _ensure_micro_estimate(food_name: str) -> dict[str, float]:
    """Await (or run) the background micro estimate for an estimated food.

    Lazy import for the same circular-import reason as above.
    """
    from backend.agent.tools.usda import ensure_micro_estimate

    return await ensure_micro_estimate(food_name)


async def resolve_micros(
    fdc_id: int, food_name: str, qty_g: float, rejected: list[str] | None = None
) -> dict[str, MicroValue]:
    """Derive an item's tracked micronutrients server-side (research R9).

    Args:
        fdc_id: USDA id (> 0), or -1 for an LLM-estimated food.
        food_name: Food name; the estimate-cache key when ``fdc_id`` is -1.
        qty_g: The item's gram weight.
        rejected: Optional collector for rejected estimate keys.

    Returns:
        A MicroValue for every stored key. For an estimated food whose cache
        row has no micros yet, waits for the background micro estimate
        started at card time (or runs it, bounded) — spec 008 research R7.
    """
    per_100g: PerHundred = {}
    if fdc_id > 0:
        try:
            inputs = await asyncio.to_thread(usda_local.micro_inputs, fdc_id)
        except usda_local.FoodDbUnavailable:
            logger.warning("Local USDA DB unavailable; micros unknown for %s", fdc_id)
            inputs = None
        if inputs is not None:
            per_100g = per_100g_from_usda(*inputs)
    else:
        cached = await _estimate_cache_lookup(food_name)
        row = dict((cached or {}).get("nutrients") or {})
        if not row.get("micros"):
            row["micros"] = await _ensure_micro_estimate(food_name)
        per_100g = per_100g_from_estimate_row(row)
    return build_item_micros(per_100g, qty_g, rejected)


__all__ = [
    "build_item_micros",
    "per_100g_from_estimate_row",
    "per_100g_from_usda",
    "resolve_micros",
    "summarise",
]
