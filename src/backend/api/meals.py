from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.orchestrator import handle_message
from backend.agent.tools.history import get_category_breakdown
from backend.agent.tools.meals import (
    MEAL_CATEGORIES,
    MealLogResult,
    _meal_label,
    soft_delete_meal,
)
from backend.agent.tools.meals import log_meal as persist_meal
from backend.api.my_meals import _scaled_result
from backend.auth.supabase import get_current_user_id
from backend.db.models import MealLog
from backend.db.redis_client import current_day_bounds, get_today_totals
from backend.db.session import get_session
from backend.ratelimit import user_rate_limiter

router = APIRouter(prefix="/meals", tags=["meals"])

# Burst limit for the LLM chat endpoint, per user per minute. Complements
# the lifetime credit quota (backend.quota): the quota caps spend, this
# caps how fast a single user can burn it / hammer the LLM.
CHAT_RATE_LIMIT = 20


async def _get_today_by_type(
    user_id: str,
    db: AsyncSession,
) -> list[dict]:
    """Return today's kcal total and item-name summary per meal_type.

    Uses the same nutrition-day window as get_today_totals so that the
    day boundary honours the configured reset hour.

    Args:
        user_id: The authenticated user's ID.
        db: Active async DB session.

    Returns:
        List of dicts with keys meal_type, kcal (float), summary (str).
    """
    today_start, today_end = current_day_bounds()

    result = await db.execute(
        select(MealLog.meal_type, MealLog.entities, MealLog.kcal)
        .where(
            MealLog.user_id == user_id,
            MealLog.logged_at >= today_start,
            MealLog.logged_at < today_end,
            MealLog.deleted_at.is_(None),
        )
        .order_by(MealLog.logged_at)
    )
    rows = result.all()

    by_type: dict[str, dict] = {}
    for meal_type, entities_raw, meal_kcal in rows:
        entities = (
            entities_raw
            if isinstance(entities_raw, list)
            else json.loads(entities_raw or "[]")
        )
        names = [item.get("food_name", "") for item in entities[:3]]
        summary = ", ".join(n for n in names if n)
        if len(entities) > 3:
            summary += f" +{len(entities) - 3} more"
        if meal_type not in by_type:
            by_type[meal_type] = {
                "meal_type": meal_type,
                "kcal": 0.0,
                "summary": summary,
            }
        by_type[meal_type]["kcal"] += float(meal_kcal or 0)

    return list(by_type.values())


class LogMealRequest(BaseModel):
    user_input: str
    conversation_id: str | None = None
    image_b64: str | None = None
    meal_type: str | None = None
    action: str | None = None  # "decompose" → break the paused meal into ingredients


@router.post(
    "/log",
    dependencies=[
        Depends(user_rate_limiter("chat", limit=CHAT_RATE_LIMIT, window_s=60))
    ],
)
async def log_meal(
    req: LogMealRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    thread_id = req.conversation_id or user_id
    checkpointer = request.app.state.checkpointer

    return await handle_message(
        user_id=user_id,
        user_input=req.user_input,
        thread_id=thread_id,
        checkpointer=checkpointer,
        image_b64=req.image_b64,
        meal_type=req.meal_type,
        action=req.action,
    )


class LogItemIn(BaseModel):
    """One resolved confirmation-card item to log directly (no LLM).

    `qty_g` is the originally resolved gram weight (the scaling base);
    `target_qty_g` is the user-edited weight before the portion multiplier.
    Extra fields (nutrients, fdc_id, macros, source, estimated, source_dish)
    are kept verbatim so the logged row carries full nutrition.
    """

    food_name: str
    qty_g: float = Field(gt=0)
    target_qty_g: float = Field(gt=0)

    model_config = ConfigDict(extra="allow")


class LogItemsRequest(BaseModel):
    """Log a confirmation card's final item set directly.

    The frontend applies removals and quantity edits locally and sends only
    the kept items; removing or re-weighing an ingredient never calls the LLM.
    Food swaps still go through the chat correction path (they need
    re-resolution) before the card is logged this way.
    """

    meal_type: str
    portion: float = Field(default=1.0, gt=0)
    items: list[LogItemIn] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


@router.post("/log-items")
async def log_items(
    req: LogItemsRequest,
    user_id: str = Depends(get_current_user_id),
) -> MealLogResult:
    """Log a client-provided resolved item set without any LLM round-trip.

    Each item is re-scaled server-side from its own nutrients (never trusting
    client macros beyond the provided gram weight + portion), then persisted
    via the same log_meal path as chat/My-Meals logging so flags, Redis
    today-totals, and the embedding enqueue all match.

    Raises:
        HTTPException 422: Invalid meal_type.
    """
    if req.meal_type not in MEAL_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid meal_type")

    item_dicts = [it.model_dump() for it in req.items]
    results = [_scaled_result(d, d["target_qty_g"], req.portion) for d in item_dicts]
    label = _meal_label(item_dicts) or None
    return await persist_meal(user_id, results, req.meal_type, label=label)


@router.delete("/log/{meal_id}", status_code=204)
async def delete_meal_log(
    meal_id: str,
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Soft-delete a meal log entry (undo within the undo window).

    Marks the row deleted_at so it disappears from today's totals and history
    queries. The row is retained for audit purposes.

    Raises:
        HTTPException 404: If no matching undeleted meal is found for this user.
    """
    deleted = await soft_delete_meal(meal_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meal not found")


@router.get("/today")
async def get_today(user_id: str = Depends(get_current_user_id)) -> dict:
    """Return today's macro totals plus a per-meal-type breakdown.

    Combines the Redis-backed totals from get_today_totals with a live
    per-meal-type breakdown built from meal_log rows in the current
    nutrition-day window.

    Args:
        user_id: Injected by the Supabase auth dependency.

    Returns:
        Dict with kcal, protein_g, fiber_g, n_meals, and by_type list.
    """
    totals = await get_today_totals(user_id)
    session_factory = get_session()
    async with session_factory() as db:
        by_type = await _get_today_by_type(user_id=user_id, db=db)
    return {**totals.model_dump(), "by_type": by_type}


class DayTrend(BaseModel):
    """One day's aggregate for the trends heatmap/sparkline."""

    date: date
    kcal: float
    protein_g: float
    carbs_g: float
    fiber_g: float
    n_meals: int
    junk_meals: int

    model_config = ConfigDict(extra="forbid")


class CategoryStat(BaseModel):
    """Per-category aggregate for the meal-category breakdown panel."""

    meal_type: str
    n_meals: int
    days_logged: int
    avg_kcal: float
    avg_protein_g: float
    avg_carbs_g: float
    avg_fat_g: float
    avg_fiber_g: float
    total_kcal: float
    share_kcal_pct: float

    model_config = ConfigDict(extra="forbid")


@router.get("/categories")
async def get_categories(
    days: int = Query(default=30, ge=1, le=366),
    user_id: str = Depends(get_current_user_id),
) -> list[CategoryStat]:
    """Per-category macro averages + frequency over the last `days` days.

    One indexed GROUP BY (see get_category_breakdown); fine at personal
    scale. Categories with no meals in the window are omitted.
    """
    rows = await get_category_breakdown(user_id, days)
    return [CategoryStat(**row) for row in rows]


@router.get("/trends")
async def get_trends(
    days: int = Query(default=91, ge=1, le=366),
    user_id: str = Depends(get_current_user_id),
) -> list[DayTrend]:
    """Per-day kcal/protein/fiber/junk aggregates for the last `days` days.

    Aggregates meal_log directly (uses ix_meal_log_user_logged_at); fine at
    personal scale and always includes today's partial day. Days with no
    meals are omitted — the frontend fills gaps as empty cells.
    """
    date_from = date.today() - timedelta(days=days - 1)
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT logged_at::date AS day, "
                "COALESCE(SUM(kcal), 0) AS kcal, "
                "COALESCE(SUM(protein_g), 0) AS protein_g, "
                "COALESCE(SUM(carbs_g), 0) AS carbs_g, "
                "COALESCE(SUM(fiber_g), 0) AS fiber_g, "
                "COUNT(*) AS n_meals, "
                "COUNT(*) FILTER (WHERE (flags->>'has_junk')::boolean) AS junk_meals "
                "FROM meal_log "
                "WHERE user_id = :user_id AND logged_at::date >= :date_from "
                "AND deleted_at IS NULL "
                "GROUP BY day ORDER BY day"
            ),
            {"user_id": user_id, "date_from": date_from},
        )
        return [
            DayTrend(
                date=row.day,
                kcal=float(row.kcal),
                protein_g=float(row.protein_g),
                carbs_g=float(row.carbs_g),
                fiber_g=float(row.fiber_g),
                n_meals=int(row.n_meals),
                junk_meals=int(row.junk_meals),
            )
            for row in result.all()
        ]
