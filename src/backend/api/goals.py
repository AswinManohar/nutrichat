from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.supabase import get_current_user_id
from backend.db.models import UserGoal
from backend.db.session import get_session

router = APIRouter(prefix="/goals", tags=["goals"])


class GoalResponse(BaseModel):
    kcal_goal: float
    protein_goal: float
    fiber_goal: float
    dietary_prefs: dict
    streak_days: int

    model_config = ConfigDict(extra="forbid")


class GoalCreate(BaseModel):
    kcal_goal: float = Field(gt=0)
    protein_goal: float = Field(gt=0)
    fiber_goal: float = Field(gt=0)
    dietary_prefs: dict = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class GoalUpdate(BaseModel):
    kcal_goal: float = Field(gt=0)
    protein_goal: float = Field(gt=0)
    fiber_goal: float = Field(gt=0)
    dietary_prefs: dict = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


def _to_response(goal: UserGoal) -> GoalResponse:
    return GoalResponse(
        kcal_goal=goal.kcal_goal,
        protein_goal=goal.protein_goal,
        fiber_goal=goal.fiber_goal,
        dietary_prefs=goal.dietary_prefs,
        streak_days=goal.streak_days,
    )


@router.get("")
async def get_goals(user_id: str = Depends(get_current_user_id)) -> GoalResponse:
    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="User has not been onboarded")
        return _to_response(goal)


@router.post("", status_code=201)
async def create_goals(
    req: GoalCreate, user_id: str = Depends(get_current_user_id)
) -> GoalResponse:
    session_factory = get_session()
    async with session_factory() as session:
        existing = await session.get(UserGoal, user_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail="User already onboarded")

        goal = UserGoal(
            user_id=user_id,
            kcal_goal=req.kcal_goal,
            protein_goal=req.protein_goal,
            fiber_goal=req.fiber_goal,
            dietary_prefs=req.dietary_prefs,
            streak_days=0,
        )
        session.add(goal)
        await session.commit()
        await session.refresh(goal)
        return _to_response(goal)


@router.put("")
async def update_goals(
    req: GoalUpdate, user_id: str = Depends(get_current_user_id)
) -> GoalResponse:
    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="User has not been onboarded")

        goal.kcal_goal = req.kcal_goal
        goal.protein_goal = req.protein_goal
        goal.fiber_goal = req.fiber_goal
        goal.dietary_prefs = req.dietary_prefs
        await session.commit()
        await session.refresh(goal)
        return _to_response(goal)
