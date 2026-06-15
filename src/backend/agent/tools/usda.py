from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re

import aiohttp
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.agent.llm import FLASH_LITE_MODEL
from backend.config import get_tunables
from backend.db.session import get_session

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

USDA_SEARCH_URL = _TUNABLES.usda.search_url

# Grammatical fillers dropped before matching so they don't count as
# required query words (e.g. "rice with chicken" -> {rice, chicken}).
_MATCH_STOPWORDS = frozenset(
    {"and", "or", "with", "the", "a", "an", "of", "in", "on", "to"}
)

_MACRO_MAP = {
    "Energy": "kcal",
    "Protein": "protein_g",
    "Carbohydrate, by difference": "carbs_g",
    "Total lipid (fat)": "fat_g",
    "Fiber, total dietary": "fiber_g",
    "Total Sugars": "sugar_g",
    "Fatty acids, total saturated": "sat_fat_g",
}

# Foundation entries often report energy only under Atwater names (in kcal),
# with no plain "Energy" row — check these in order.
_ENERGY_KEYS = (
    "Energy",
    "Energy (Atwater General Factors)",
    "Energy (Atwater Specific Factors)",
)

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

    # Plan A — LLM nutrition estimation fallback (agent/tools/usda.py
    # estimate_nutrition_llm). "USDA" for real FoodData Central matches
    # (incl. cache hits), "LLM_ESTIMATE" when no confident USDA match was
    # found and the model estimated macros instead.
    source: str = "USDA"
    estimated: bool = False


class NutritionEstimate(BaseModel):
    """LLM-estimated nutrition for a food at a specific gram weight.

    Used by estimate_nutrition_llm() as the pydantic-ai structured output
    type. All values are TOTALS for the given qty_g, not per-100g.
    """

    kcal: float = Field(ge=0.0)
    protein_g: float = Field(ge=0.0)
    carbs_g: float = Field(ge=0.0)
    fat_g: float = Field(ge=0.0)
    fiber_g: float = Field(ge=0.0)
    sugar_g: float = Field(ge=0.0)
    sat_fat_g: float = Field(ge=0.0)

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


async def _cache_lookup(food_name: str) -> dict | None:
    """Check Postgres food_source for a real USDA match (case-insensitive).

    Excludes LLM_ESTIMATE rows — those are looked up separately via
    _estimate_cache_lookup so a previous estimate never masquerades as a
    confident USDA hit.
    """
    try:
        async with get_session()() as session:
            result = await session.execute(
                text(
                    "SELECT fdc_id, food_name, nutrients FROM food_source "
                    "WHERE food_name ILIKE :name AND source_db = 'FDC' LIMIT 1"
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


def _normalize_food_name(food_name: str) -> str:
    """Lowercase + collapse whitespace for stable LLM-estimate cache keys."""
    return " ".join(food_name.lower().split())


def _estimate_fdc_id(normalized_name: str) -> int:
    """Deterministic negative fdc_id for an LLM-estimate cache row.

    food_source.fdc_id is the primary key, so estimates can't all share
    -1 — hash the normalized food name into a stable negative integer
    instead (collisions across distinct foods are astronomically
    unlikely and self-heal via ON CONFLICT DO NOTHING + re-estimate).
    """
    digest = hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()
    return -1 * (int(digest[:15], 16) % 2_000_000_000 + 1)


async def _estimate_cache_lookup(food_name: str) -> dict | None:
    """Check food_source for a previously cached LLM estimate (per-100g)."""
    normalized = _normalize_food_name(food_name)
    try:
        async with get_session()() as session:
            result = await session.execute(
                text(
                    "SELECT fdc_id, food_name, nutrients FROM food_source "
                    "WHERE food_name = :name AND source_db = 'LLM_ESTIMATE' LIMIT 1"
                ),
                {"name": normalized},
            )
            row = result.fetchone()
            if row:
                return {"fdc_id": row[0], "food_name": row[1], "nutrients": row[2]}
    except SQLAlchemyError as exc:
        logger.warning("Estimate cache lookup failed: %s", exc)
    return None


async def _estimate_cache_write(food_name: str, nutrients_per_100g: dict) -> None:
    """Cache an LLM nutrition estimate (per-100g) keyed by normalized name."""
    normalized = _normalize_food_name(food_name)
    fdc_id = _estimate_fdc_id(normalized)
    try:
        async with get_session()() as session:
            await session.execute(
                text(
                    "INSERT INTO food_source "
                    "(fdc_id, food_name, nutrients, nutrients_count, source_db) "
                    "VALUES (:fdc_id, :name, CAST(:nutrients AS jsonb), :count, "
                    "'LLM_ESTIMATE') "
                    "ON CONFLICT (fdc_id) DO NOTHING"
                ),
                {
                    "fdc_id": fdc_id,
                    "name": normalized,
                    "nutrients": json.dumps(nutrients_per_100g),
                    "count": len(nutrients_per_100g),
                },
            )
            await session.commit()
    except SQLAlchemyError as exc:
        logger.warning("Estimate cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _singularize(token: str) -> str:
    """Crude, symmetric singularizer so plurals match (eggs->egg).

    Applied to both query and description tokens, so even rough rules are
    safe for matching — both sides normalize identically. Handles the
    common English plural endings; leaves short tokens alone.
    """
    if len(token) <= 3:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith(("ses", "shes", "ches", "xes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokenize(text_value: str) -> set[str]:
    """Lowercase, strip punctuation, drop stopwords, singularize."""
    raw = re.sub(r"[^\w\s]", " ", text_value.lower()).split()
    return {_singularize(t) for t in raw if t not in _MATCH_STOPWORDS}


def _confidence(query: str, description: str) -> float:
    """Match confidence as query-word coverage by the FDC description.

    Returns the fraction of the user's food words that appear in the FDC
    description (after singularizing and dropping filler words). Coverage,
    not Jaccard: FDC descriptions are verbose ("Rice, white, long-grain,
    regular, raw, enriched") and Jaccard's union denominator wrongly tanks
    correct matches. Coverage asks the right question — "is the food the
    user named actually in this description?" — so "white rice" and "banana"
    score 1.0, while "chicken biryani" vs "Chicken spread" scores 0.5
    (only "chicken" matched) and falls below the floor.
    """
    a = _tokenize(query)
    b = _tokenize(description)
    if not a or not b:
        return 0.5
    return round(len(a & b) / len(a), 3)


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


def _energy_kcal(raw: dict[str, tuple[float, str]]) -> float:
    """First non-zero energy value across the known FDC energy names."""
    for key in _ENERGY_KEYS:
        if key in raw and raw[key][0] > 0:
            return raw[key][0]
    return 0.0


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
    macros["kcal"] = round(_energy_kcal(raw) * scale, 2)
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
    macros["kcal"] = round(
        next((_val(k) for k in _ENERGY_KEYS if _val(k) > 0), 0.0) * scale, 2
    )
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
# LLM nutrition estimate (Plan A fallback)
# ---------------------------------------------------------------------------

_ESTIMATE_SYSTEM = _TUNABLES.prompts.nutrition_estimate_system

_estimate_agent = Agent(
    GoogleModel(FLASH_LITE_MODEL),
    output_type=NutritionEstimate,
    system_prompt=_ESTIMATE_SYSTEM,
)


def _estimate_result(entity, per_100g: dict[str, float]) -> USDAResult:
    """Build a USDAResult tagged as an LLM estimate from per-100g macros."""
    scale = entity.qty_g / 100.0
    macros = {field: round(val * scale, 2) for field, val in per_100g.items()}
    return USDAResult(
        fdc_id=-1,
        food_name=entity.food_name,
        qty_g=entity.qty_g,
        match_confidence=_TUNABLES.usda.llm_estimate_confidence,
        candidates=[],
        **macros,
        nutrients={},
        source="LLM_ESTIMATE",
        estimated=True,
    )


async def estimate_nutrition_llm(food_name: str, qty_g: float) -> USDAResult:
    """Estimate nutrition for a food the USDA database can't confidently match.

    Cache-first: checks food_source for a previously cached LLM_ESTIMATE row
    (keyed by normalized food name, stored per-100g) before calling Gemini.

    Args:
        food_name: Free-text food name, e.g. "chicken biryani".
        qty_g: Gram weight of the portion.

    Returns:
        USDAResult with fdc_id=-1, source="LLM_ESTIMATE", estimated=True,
        and macros scaled to qty_g.
    """
    cached = await _estimate_cache_lookup(food_name)
    if cached:
        per_100g = {k: float(v) for k, v in cached["nutrients"].items()}
        entity_like = _EntityShim(food_name=cached["food_name"], qty_g=qty_g)
        return _estimate_result(entity_like, per_100g)

    entity_like = _EntityShim(food_name=food_name, qty_g=qty_g)
    try:
        run = await _estimate_agent.run(f"Food: {food_name}\nQuantity: {qty_g}g")
        estimate = run.output
    except Exception as exc:  # noqa: BLE001 — any LLM/provider failure -> miss
        logger.error("LLM nutrition estimate failed for %s: %s", food_name, exc)
        return _miss_result(entity_like)

    # Store per-100g so qty scaling works the same as USDA cache rows.
    scale_to_100 = 100.0 / qty_g if qty_g else 0.0
    per_100g = {
        field: getattr(estimate, field) * scale_to_100
        for field in (
            "kcal",
            "protein_g",
            "carbs_g",
            "fat_g",
            "fiber_g",
            "sugar_g",
            "sat_fat_g",
        )
    }
    await _estimate_cache_write(food_name, per_100g)

    return USDAResult(
        fdc_id=-1,
        food_name=food_name,
        qty_g=qty_g,
        match_confidence=_TUNABLES.usda.llm_estimate_confidence,
        candidates=[],
        kcal=estimate.kcal,
        protein_g=estimate.protein_g,
        carbs_g=estimate.carbs_g,
        fat_g=estimate.fat_g,
        fiber_g=estimate.fiber_g,
        sugar_g=estimate.sugar_g,
        sat_fat_g=estimate.sat_fat_g,
        nutrients={},
        source="LLM_ESTIMATE",
        estimated=True,
    )


class _EntityShim:
    """Minimal food_name/qty_g object for reusing _miss_result/_estimate_result."""

    def __init__(self, food_name: str, qty_g: float) -> None:
        self.food_name = food_name
        self.qty_g = qty_g


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------


async def _fetch_one(session: aiohttp.ClientSession, entity) -> USDAResult:
    """Fetch one entity: cache-first, FDC on miss, write cache on miss.

    Confidence gate (Plan A): if the best USDA match's match_confidence is
    below usda.match_confidence_floor, or there is no usable match at all
    (fdc_id == -1), discard the weak hit and fall back to
    estimate_nutrition_llm() instead.
    """
    result = await _fetch_usda(session, entity)

    floor = _TUNABLES.usda.match_confidence_floor
    if result.fdc_id == -1 or result.match_confidence < floor:
        return await estimate_nutrition_llm(entity.food_name, entity.qty_g)
    return result


async def _fetch_usda(session: aiohttp.ClientSession, entity) -> USDAResult:
    """Fetch one entity from the real USDA pipeline: cache-first, FDC on miss."""
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
