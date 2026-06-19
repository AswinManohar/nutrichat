from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text as sa_text

from backend.agent.orchestrator import handle_message
from backend.agent.tools.history import get_category_breakdown
from backend.agent.tools.meals import soft_delete_meal
from backend.auth.supabase import get_current_user_id
from backend.db.redis_client import TodayTotals, get_today_totals
from backend.db.session import get_session

router = APIRouter(prefix="/meals", tags=["meals"])


class LogMealRequest(BaseModel):
    user_input: str
    conversation_id: str | None = None
    image_b64: str | None = None
    meal_type: str | None = None
    action: str | None = None  # "decompose" → break the paused meal into ingredients


@router.post("/log")
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
async def get_today(user_id: str = Depends(get_current_user_id)) -> TodayTotals:
    return await get_today_totals(user_id)


class DayTrend(BaseModel):
    """One day's aggregate for the trends heatmap/sparkline."""

    date: date
    kcal: float
    protein_g: float
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
                fiber_g=float(row.fiber_g),
                n_meals=int(row.n_meals),
                junk_meals=int(row.junk_meals),
            )
            for row in result.all()
        ]
