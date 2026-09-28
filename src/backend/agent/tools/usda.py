from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os

import aiohttp
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.agent.llm import FLASH_LITE_MODEL
from backend.agent.tools import usda_local
from backend.agent.tools.usda_match import (
    _ENERGY_KEYS,
    _MACRO_MAP,
    _confidence,
    _energy_kcal,
)
from backend.config import get_tunables
from backend.db.session import get_session

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

USDA_SEARCH_URL = _TUNABLES.usda.search_url

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class NutrientValue(BaseModel):
    amount: float
    unit: str  # g, mg, mcg, kcal


class CandidateDetail(BaseModel):
    """One candidate's nutrition, for the confirm card's picker (spec 003).

    Same shape as ``FoodSearchResult`` minus the request-scaled fields — the
    client scales for preview (data-model.md). ``name`` matches the
    corresponding entry in the sibling ``candidates: list[str]``, same
    order.
    """

    fdc_id: int
    name: str
    data_type: str
    kcal_per_100g: float = Field(ge=0.0)
    protein_g_per_100g: float = Field(ge=0.0)

    model_config = ConfigDict(extra="forbid")


class USDAResult(BaseModel):
    fdc_id: int
    food_name: str
    qty_g: float
    match_confidence: float
    candidates: list[str]
    # Spec 003, "Compare the suggested alternatives" (US2): per-candidate
    # nutrition, same order as `candidates`. Empty for estimated items and
    # the live-FDC path (only usda_local.lookup's pool populates it, T034).
    candidate_details: list[CandidateDetail] = []

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
    # Set by usda_batch_node from the originating FoodEntity when this result
    # came from auto-decomposing a composite dish; None otherwise.
    source_dish: str | None = None
    # Carried from the originating FoodEntity: True for a prepared/multi-
    # ingredient dish that can still be broken into ingredients. Lets the
    # frontend offer "Break into ingredients" only where it makes sense.
    is_composite: bool = False
    # Spec 003 research R9: the user's original words for this item, set by
    # usda_batch_node from the originating FoodEntity.food_name when that
    # differs from the matched food_name (e.g. "toast" -> "Bread, white,
    # toasted"). None when the matched name already carries the user's
    # words, so the picker's initial query has something to prefill with.
    input_phrase: str | None = None


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


def _result_from_local(entity, match: usda_local.LocalMatch) -> USDAResult:
    """Build a USDAResult from a bundled-SQLite LocalMatch (per 100g)."""
    scale = entity.qty_g / 100.0
    macros = {
        field: round(match.macros_per_100g[field] * scale, 2)
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
    nutrients = {
        name: NutrientValue(amount=round(v["amount"] * scale, 3), unit=v["unit"])
        for name, v in match.nutrients_per_100g.items()
    }
    return USDAResult(
        fdc_id=match.fdc_id,
        food_name=match.description,
        qty_g=entity.qty_g,
        match_confidence=match.match_confidence,
        candidates=match.candidates,
        candidate_details=[
            CandidateDetail(**detail) for detail in match.candidate_details
        ],
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

# Thinking off (extraction-tier): estimation is a single structured-output
# call on the interactive card-render path — don't pay the dynamic-thinking
# latency (see token_limits.extraction_thinking_budget).
_estimate_agent = Agent(
    GoogleModel(FLASH_LITE_MODEL),
    output_type=NutritionEstimate,
    system_prompt=_ESTIMATE_SYSTEM,
    model_settings=GoogleModelSettings(
        google_thinking_config={
            "thinking_budget": _TUNABLES.token_limits.extraction_thinking_budget
        }
    ),
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


_local_unavailable_logged = False


def _use_local() -> bool:
    """Whether the bundled-SQLite local read path should be used.

    Fail-soft: if use_local_db is on but the database isn't actually
    available, log once (never per lookup) and fall back to the FDC API
    path instead of taking the bot down.
    """
    global _local_unavailable_logged
    if not _TUNABLES.usda.use_local_db:
        return False
    if usda_local.is_available():
        return True
    if not _local_unavailable_logged:
        logger.error(
            "usda.use_local_db is true but the local USDA database is "
            "unavailable; falling back to the FDC API."
        )
        _local_unavailable_logged = True
    return False


async def _fetch_one(session: aiohttp.ClientSession | None, entity) -> USDAResult:
    """Fetch one entity: local SQLite or cache-first FDC, then confidence gate.

    Confidence gate (Plan A): if the best USDA match's match_confidence is
    below usda.match_confidence_floor, or there is no usable match at all
    (fdc_id == -1), discard the weak hit and fall back to
    estimate_nutrition_llm() instead.
    """
    if _use_local():
        match = await asyncio.to_thread(
            usda_local.lookup,
            entity.food_name,
            pool_size=_TUNABLES.usda.candidate_pool_size,
            max_candidates=_TUNABLES.usda.max_candidates,
        )
        result = _result_from_local(entity, match) if match else _miss_result(entity)
    else:
        result = await _fetch_usda_api(session, entity)

    floor = _TUNABLES.usda.match_confidence_floor
    if result.fdc_id == -1 or result.match_confidence < floor:
        return await estimate_nutrition_llm(entity.food_name, entity.qty_g)
    return result


async def _fetch_usda_api(session: aiohttp.ClientSession, entity) -> USDAResult:
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

    By default (usda.use_local_db) every lookup is served from the SQLite
    copy bundled in the image, so no network or Postgres access happens at
    all. On the rollback path the old behaviour applies: Postgres
    food_source cache first, FDC API on miss, result written back to cache.

    Either way, entities whose best match falls below
    usda.match_confidence_floor are resolved by estimate_nutrition_llm.

    Args:
        entities: List of FoodEntity with food_name and qty_g.

    Returns:
        List of USDAResult in same order. Failed lookups have fdc_id=-1.
    """
    if _use_local():
        return list(await asyncio.gather(*[_fetch_one(None, e) for e in entities]))

    async with aiohttp.ClientSession() as session:
        return list(await asyncio.gather(*[_fetch_one(session, e) for e in entities]))
