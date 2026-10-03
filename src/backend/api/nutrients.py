"""GET /nutrients/daily — per-day tracked micronutrient totals (spec 008).

Computed from meal_log on every call (FR-018); the data source for the
future micronutrient visualization (FR-017). Contract:
specs/008-fixed-micronutrients/contracts/daily-totals.md.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.auth.supabase import get_current_user_id
from backend.nutrients.daily import get_daily_micros, validate_request

router = APIRouter(prefix="/nutrients", tags=["nutrients"])


@router.get("/daily")
async def daily_micros(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    keys: str | None = Query(default=None, description="comma-separated keys"),
    meals: bool = Query(default=False),
    user_id: str = Depends(get_current_user_id),
) -> JSONResponse:
    """Return every nutrition day in ``[from, to]`` with its micro totals.

    Raises:
        HTTPException: 422 for a range over 365 days, an inverted range, or
            an unknown nutrient key.
    """
    key_list = [k.strip() for k in keys.split(",") if k.strip()] if keys else None
    try:
        validate_request(date_from, date_to, key_list)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    resp = await get_daily_micros(user_id, date_from, date_to, key_list, meals)
    return JSONResponse(resp.model_dump(mode="json", by_alias=True, exclude_none=True))
