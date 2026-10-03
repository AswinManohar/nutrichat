"""GET /foods/search and GET /foods/{fdc_id} (spec 003, contracts/foods-api.md).

Free-text search of the bundled USDA reference database, and building a
ready-to-log card item for a chosen food. Both endpoints are read-only,
authenticated, rate-limited, and run the synchronous SQLite reads via
``asyncio.to_thread`` (research R8, T002's finding in tests/test_foods_api.py).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

import logfire
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.tools import usda_local
from backend.agent.tools.usda import (
    NULLABLE_MACROS,
    USDAResult,
    scale_macro,
)
from backend.auth.supabase import get_current_user_id
from backend.nutrients.resolve import resolve_micros
from backend.ratelimit import user_rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/foods", tags=["foods"])

_DataType = Literal["foundation", "sr_legacy", "survey_fndds"]


class FoodSearchResult(BaseModel):
    """One search hit, preview-scaled to the request's ``qty_g``."""

    fdc_id: int
    name: str
    data_type: _DataType
    kcal_per_100g: float = Field(ge=0.0)
    protein_g_per_100g: float = Field(ge=0.0)
    kcal: float = Field(ge=0.0)
    protein_g: float = Field(ge=0.0)

    model_config = ConfigDict(extra="forbid")


class FoodSearchResponse(BaseModel):
    """Response body for GET /foods/search."""

    query: str
    normalized_query: str
    results: list[FoodSearchResult]

    model_config = ConfigDict(extra="forbid")


def _to_search_result(hit: usda_local.LocalFoodHit, qty_g: float) -> FoodSearchResult:
    """Scale one LocalFoodHit's preview macros to ``qty_g``."""
    scale = qty_g / 100.0
    return FoodSearchResult(
        fdc_id=hit.fdc_id,
        name=hit.name,
        data_type=hit.data_type,
        kcal_per_100g=hit.kcal_per_100g,
        protein_g_per_100g=hit.protein_g_per_100g,
        kcal=round(hit.kcal_per_100g * scale, 1),
        protein_g=round(hit.protein_g_per_100g * scale, 1),
    )


@router.get(
    "/search",
    dependencies=[Depends(user_rate_limiter("foods_search", limit=60, window_s=60))],
)
async def search_foods(
    q: str = Query(min_length=2, max_length=100),
    qty_g: float = Query(default=100.0, gt=0, le=5000),
    limit: int = Query(default=10, ge=1, le=20),
    user_id: str = Depends(get_current_user_id),
) -> FoodSearchResponse:
    """Free-text search of the bundled USDA reference database.

    Args:
        q: Free-text food name, trimmed length 2-100.
        qty_g: Gram weight used only for the preview kcal/protein_g,
            > 0 and <= 5000. Defaults to 100.
        limit: Max results to return, 1-20. Defaults to 10.
        user_id: Authenticated Supabase Auth UUID.

    Returns:
        FoodSearchResponse with results ordered best-first. An empty
        `results` list means no match (not an error).

    Raises:
        HTTPException 503: The local USDA reference database is unavailable.
    """
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="q must be at least 2 characters")

    started = time.monotonic()
    try:
        hits = await _search_in_thread(query, limit)
    except usda_local.FoodDbUnavailable:
        raise HTTPException(status_code=503, detail="food_search_unavailable") from None

    latency_ms = round((time.monotonic() - started) * 1000, 1)
    logfire.info(
        "foods_search",
        user_id=user_id,
        query_len=len(query),
        result_count=len(hits),
        latency_ms=latency_ms,
    )

    results = [_to_search_result(h, qty_g) for h in hits]
    normalized = usda_local._normalize_preparation(query)
    return FoodSearchResponse(query=query, normalized_query=normalized, results=results)


async def _search_in_thread(query: str, limit: int) -> list[usda_local.LocalFoodHit]:
    """Run ``usda_local.search_foods`` off the event loop (research R8)."""
    return await asyncio.to_thread(usda_local.search_foods, query, limit)


@router.get(
    "/{fdc_id}",
    dependencies=[Depends(user_rate_limiter("foods_get", limit=30, window_s=60))],
)
async def get_food(
    fdc_id: int,
    qty_g: float = Query(gt=0, le=5000),
    user_id: str = Depends(get_current_user_id),
) -> USDAResult:
    """Build a ready-to-log card item for a chosen food, scaled to ``qty_g``.

    Args:
        fdc_id: USDA FoodData Central id to load.
        qty_g: Gram weight to scale to, > 0 and <= 5000.
        user_id: Authenticated Supabase Auth UUID.

    Returns:
        The existing card-item shape (USDAResult) with source="usda_local",
        estimated=False, match_confidence=1.0, and empty candidates /
        candidate_details.

    Raises:
        HTTPException 404: Unknown fdc_id.
        HTTPException 503: The local USDA reference database is unavailable.
    """
    try:
        food = await asyncio.to_thread(usda_local.get_food, fdc_id)
    except usda_local.FoodDbUnavailable:
        raise HTTPException(status_code=503, detail="food_search_unavailable") from None

    if food is None:
        raise HTTPException(status_code=404, detail="Unknown fdc_id")

    scale = qty_g / 100.0
    macros = {
        field: scale_macro(food.macros_per_100g[field], scale)
        for field in ("kcal", *NULLABLE_MACROS)
    }
    micros = await resolve_micros(food.fdc_id, food.name, qty_g)
    return USDAResult(
        fdc_id=food.fdc_id,
        food_name=food.name,
        qty_g=qty_g,
        match_confidence=1.0,
        candidates=[],
        candidate_details=[],
        micros=micros,
        source="usda_local",
        estimated=False,
        **macros,
    )
