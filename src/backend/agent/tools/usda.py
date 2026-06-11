from __future__ import annotations

import asyncio
import json
import logging
import os

import aiohttp
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.config import get_tunables
from backend.db.session import get_session

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

USDA_SEARCH_URL = _TUNABLES.usda.search_url

_MACRO_MAP = {
    "Energy": "kcal",
    "Protein": "protein_g",
    "Carbohydrate, by difference": "carbs_g",
    "Total lipid (fat)": "fat_g",
    "Fiber, total dietary": "fiber_g",
    "Total Sugars": "sugar_g",
    "Fatty acids, total saturated": "sat_fat_g",
}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class NutrientValue(BaseModel):
    amount: float
    unit: str  # g, mg, mcg, kcal


class USDAResult(BaseModel):
    fdc_id: int
    food_name: str
    qty_g: float
    match_confidence: float
    candidates: list[str]

    # Promoted macros scaled to qty_g
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sugar_g: float
    sat_fat_g: float

    # Full nutrient breakdown scaled to qty_g (~50 nutrients)
    nutrients: dict[str, NutrientValue]


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


async def _cache_lookup(food_name: str) -> dict | None:
    """Check Postgres food_source for a matching food name (case-insensitive)."""
    try:
        async with get_session()() as session:
            result = await session.execute(
                text(
                    "SELECT fdc_id, food_name, nutrients FROM food_source "
                    "WHERE food_name ILIKE :name LIMIT 1"
                ),
                {"name": f"%{food_name}%"},
            )
            row = result.fetchone()
            if row:
                return {"fdc_id": row[0], "food_name": row[1], "nutrients": row[2]}
    except SQLAlchemyError as exc:
        logger.warning("Cache lookup failed: %s", exc)
    return None


async def _cache_write(fdc_id: int, food_name: str, nutrients: dict) -> None:
    """Write a new food_source row. Silently ignores duplicate fdc_id."""
    try:
        async with get_session()() as session:
            await session.execute(
                text(
                    "INSERT INTO food_source "
                    "(fdc_id, food_name, nutrients, nutrients_count, source_db) "
                    "VALUES (:fdc_id, :name, CAST(:nutrients AS jsonb), :count, 'FDC') "
                    "ON CONFLICT (fdc_id) DO NOTHING"
                ),
                {
                    "fdc_id": fdc_id,
                    "name": food_name,
                    "nutrients": json.dumps(nutrients),
                    "count": len(nutrients),
                },
            )
            await session.commit()
    except SQLAlchemyError as exc:
        logger.warning("Cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _confidence(query: str, description: str) -> float:
    """Jaccard similarity between query words and FDC description words."""
    a = set(query.lower().split())
    b = set(description.lower().split())
    if not a or not b:
        return 0.5
    return round(len(a & b) / len(a | b), 3)


def _miss_result(entity) -> USDAResult:
    return USDAResult(
        fdc_id=-1,
        food_name=entity.food_name,
        qty_g=entity.qty_g,
        match_confidence=0.0,
        candidates=[],
        kcal=0.0,
        protein_g=0.0,
        carbs_g=0.0,
        fat_g=0.0,
        fiber_g=0.0,
        sugar_g=0.0,
        sat_fat_g=0.0,
        nutrients={},
    )


def _nutrients_by_name(food_nutrients: list[dict]) -> dict[str, tuple[float, str]]:
    """Key FDC nutrient entries by name, keeping kcal when Energy repeats.

    FDC lists "Energy" twice — once in kcal and once in kJ. A naive
    name-keyed dict lets the kJ row overwrite kcal (a ~4.2x calorie
    inflation bug), so the kcal entry always wins here.
    """
    raw: dict[str, tuple[float, str]] = {}
    for n in food_nutrients:
        name = n.get("nutrientName", "")
        unit = n.get("unitName", "g").lower()
        if name == "Energy" and name in raw and unit != "kcal":
            continue  # keep the kcal entry already stored
        raw[name] = (float(n.get("value", 0.0)), unit)
    return raw


def _parse_fdc_response(data: dict, entity) -> USDAResult | None:
    foods = data.get("foods", [])
    if not foods:
        return None

    top = foods[0]
    raw = _nutrients_by_name(top.get("foodNutrients", []))

    scale = entity.qty_g / 100.0
    macros = {
        field: round(raw.get(fdc_name, (0.0, "g"))[0] * scale, 2)
        for fdc_name, field in _MACRO_MAP.items()
    }
    nutrients = {
        name: NutrientValue(amount=round(val * scale, 3), unit=unit)
        for name, (val, unit) in raw.items()
    }
    candidates = [f["description"] for f in foods[:3]]

    return USDAResult(
        fdc_id=top["fdcId"],
        food_name=top["description"],
        qty_g=entity.qty_g,
        match_confidence=_confidence(entity.food_name, top["description"]),
        candidates=candidates,
        **macros,
        nutrients=nutrients,
    )


def _result_from_cache(cached: dict, entity) -> USDAResult:
    """Build a USDAResult from a Postgres cache row (nutrients stored per 100g)."""
    scale = entity.qty_g / 100.0
    raw = cached["nutrients"]  # dict[str, {amount, unit}]

    def _val(name: str) -> float:
        v = raw.get(name, {})
        return float(v.get("amount", 0.0)) if isinstance(v, dict) else float(v)

    macros = {
        field: round(_val(fdc_name) * scale, 2)
        for fdc_name, field in _MACRO_MAP.items()
    }
    nutrients = {
        name: NutrientValue(
            amount=(
                round(float(v.get("amount", 0)) * scale, 3)
                if isinstance(v, dict)
                else 0.0
            ),
            unit=v.get("unit", "g") if isinstance(v, dict) else "g",
        )
        for name, v in raw.items()
    }
    return USDAResult(
        fdc_id=cached["fdc_id"],
        food_name=cached["food_name"],
        qty_g=entity.qty_g,
        match_confidence=_TUNABLES.usda.cache_hit_confidence,
        candidates=[],
        **macros,
        nutrients=nutrients,
    )


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------


async def _fetch_one(session: aiohttp.ClientSession, entity) -> USDAResult:
    """Fetch one entity: cache-first, FDC on miss, write cache on miss."""
    cached = await _cache_lookup(entity.food_name)
    if cached:
        return _result_from_cache(cached, entity)

    api_key = os.environ.get("USDA_API_KEY", "DEMO_KEY")
    params = {
        "api_key": api_key,
        "query": entity.food_name,
        "dataType": _TUNABLES.usda.data_types,
        "pageSize": _TUNABLES.usda.page_size,
    }

    data: dict | None = None
    max_attempts = _TUNABLES.usda.max_attempts
    for attempt in range(max_attempts):
        try:
            async with session.get(
                USDA_SEARCH_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=_TUNABLES.usda.request_timeout_s),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            break
        # aiohttp timeouts surface as asyncio.TimeoutError (ClientTimeout is
        # the config object, not an exception class).
        except (TimeoutError, aiohttp.ClientError) as exc:
            if attempt == max_attempts - 1:
                logger.error(
                    "FDC request failed after retry for %s: %s", entity.food_name, exc
                )
                return _miss_result(entity)
            await asyncio.sleep(_TUNABLES.usda.retry_backoff_s)

    if data is None:
        return _miss_result(entity)

    result = _parse_fdc_response(data, entity)
    if result is None:
        return _miss_result(entity)

    # Cache raw per-100g nutrients for future hits (kcal-preferring dedup).
    raw_per_100g = {
        name: {"amount": amount, "unit": unit}
        for name, (amount, unit) in _nutrients_by_name(
            data["foods"][0].get("foodNutrients", [])
        ).items()
    }
    await _cache_write(result.fdc_id, result.food_name, raw_per_100g)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def usda_lookup_batch(entities: list) -> list[USDAResult]:
    """Fetch USDA nutrients for multiple entities in parallel.

    Checks Postgres food_source cache first. Falls back to FDC API on miss
    and writes the result back to cache.

    Args:
        entities: List of FoodEntity with food_name and qty_g.

    Returns:
        List of USDAResult in same order. Failed lookups have fdc_id=-1.

    Raises:
        aiohttp.ClientError: If FDC API is unreachable after retries.
    """
    async with aiohttp.ClientSession() as session:
        return list(await asyncio.gather(*[_fetch_one(session, e) for e in entities]))
