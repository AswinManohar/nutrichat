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
from backend.core.nutrition_day import nutrition_today
from backend.nutrients.daily import get_daily_micros, resolve_range, validate_request

router = APIRouter(prefix="/nutrients", tags=["nutrients"])


@router.get("/daily")
async def daily_micros(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    days: int | None = Query(
        default=None, description="last N nutrition days ending today"
    ),
    keys: str | None = Query(default=None, description="comma-separated keys"),
    meals: bool = Query(default=False),
    user_id: str = Depends(get_current_user_id),
) -> JSONResponse:
    """Return every nutrition day in the range with its micro totals.

    The range is ``[from, to]``, or the last ``days`` nutrition days ending
    today.

    Raises:
        HTTPException: 422 for a range over 365 days, an inverted range, a
            missing or doubled range, or an unknown nutrient key.
    """
    key_list = [k.strip() for k in keys.split(",") if k.strip()] if keys else None
    try:
        start, end = resolve_range(date_from, date_to, days, nutrition_today())
        validate_request(start, end, key_list)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    resp = await get_daily_micros(user_id, start, end, key_list, meals)
    return JSONResponse(resp.model_dump(mode="json", by_alias=True, exclude_none=True))
