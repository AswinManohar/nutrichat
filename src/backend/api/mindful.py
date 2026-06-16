from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from backend.agent.tools.mindful import (
    NutrientAmount,
    SafetyAlert,
    evaluate_safety,
    get_daily_intake,
)
from backend.auth.supabase import get_current_user_id
from backend.db.models import UserGoal
from backend.db.session import get_session

router = APIRouter(prefix="/mindful", tags=["mindful"])


class MindfulToday(BaseModel):
    tracking_mode: str
    date: date
    nutrients: list[NutrientAmount]
    alerts: list[SafetyAlert]

    model_config = ConfigDict(extra="forbid")


@router.get("/today")
async def get_today(user_id: str = Depends(get_current_user_id)) -> MindfulToday:
    """Absolute nutrient amounts consumed today + any UL safety breaches.

    Goal-mode users may call this too; the frontend only routes mindful users
    to the mindful dashboard view.
    """
    today = date.today()
    async with get_session()() as session:
        goal = await session.get(UserGoal, user_id)
        tracking_mode = (goal.tracking_mode or "goals") if goal is not None else "goals"

    nutrients = await get_daily_intake(user_id, today)
    alerts = evaluate_safety(nutrients)
    return MindfulToday(
        tracking_mode=tracking_mode,
        date=today,
        nutrients=nutrients,
        alerts=alerts,
    )
