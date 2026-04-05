from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import aiohttp
from pydantic import BaseModel
from sqlalchemy import select, text

from backend.db.session import get_session

logger = logging.getLogger(__name__)

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

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


async def _cache_lookup(food_name: str) -> Optional[dict]:
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
    except Exception as exc:
        logger.warning("Cache lookup failed: %s", exc)
    return None


async def _cache_write(fdc_id: int, food_name: str, nutrients: dict) -> None:
    """Write a new food_source row. Silently ignores duplicate fdc_id."""
    try:
        async with get_session()() as session:
            await session.execute(
                text(
                    "INSERT INTO food_source (fdc_id, food_name, nutrients, nutrients_count, source_db) "
                    "VALUES (:fdc_id, :name, CAST(:nutrients AS jsonb), :count, 'FDC') "
                    "ON CONFLICT (fdc_id) DO NOTHING"
                ),
                {
                    "fdc_id": fdc_id,
                    "name": food_name,
                    "nutrients": __import__("json").dumps(nutrients),
                    "count": len(nutrients),
                },
            )
            await session.commit()
    except Exception as exc:
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
    from backend.agent.tools.meals import FoodEntity  # avoid circular at module level
    return USDAResult(
        fdc_id=-1, food_name=entity.food_name, qty_g=entity.qty_g,
        match_confidence=0.0, candidates=[],
        kcal=0.0, protein_g=0.0, carbs_g=0.0, fat_g=0.0,
        fiber_g=0.0, sugar_g=0.0, sat_fat_g=0.0, nutrients={},
    )


def _parse_fdc_response(data: dict, entity) -> Optional[USDAResult]:
    foods = data.get("foods", [])
    if not foods:
        return None

    top = foods[0]
    raw: dict[str, tuple[float, str]] = {}
    for n in top.get("foodNutrients", []):
        name = n.get("nutrientName", "")
        raw[name] = (float(n.get("value", 0.0)), n.get("unitName", "g").lower())

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
            amount=round(float(v.get("amount", 0)) * scale, 3) if isinstance(v, dict) else 0.0,
            unit=v.get("unit", "g") if isinstance(v, dict) else "g",
        )
        for name, v in raw.items()
    }
    return USDAResult(
        fdc_id=cached["fdc_id"],
        food_name=cached["food_name"],
        qty_g=entity.qty_g,
        match_confidence=0.95,
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
        "dataType": "Foundation,SR Legacy",
        "pageSize": 5,
    }

    data: Optional[dict] = None
    for attempt in range(2):
        try:
            async with session.get(
                USDA_SEARCH_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            break
        except (aiohttp.ClientTimeout, aiohttp.ClientError) as exc:
            if attempt == 1:
                logger.error("FDC request failed after retry for %s: %s", entity.food_name, exc)
                return _miss_result(entity)
            await asyncio.sleep(1.0)

    if data is None:
        return _miss_result(entity)

    result = _parse_fdc_response(data, entity)
    if result is None:
        return _miss_result(entity)

    # Cache raw per-100g nutrients for future hits
    raw_per_100g = {
        n["nutrientName"]: {"amount": n.get("value", 0.0), "unit": n.get("unitName", "g")}
        for n in data["foods"][0].get("foodNutrients", [])
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
        return list(await asyncio.gather(
            *[_fetch_one(session, e) for e in entities]
        ))
