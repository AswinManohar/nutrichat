from __future__ import annotations

import logging
from typing import Literal, get_args

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.auth.supabase import get_current_user_id
from backend.db.models import UserGoal
from backend.db.session import get_session
from backend.safety import profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/goals", tags=["goals"])

TrackingMode = Literal["goals", "mindful"]
Condition = Literal["diabetes", "prediabetes", "hypertension", "ckd"]
_CONDITIONS = frozenset(get_args(Condition))


class GoalResponse(BaseModel):
    tracking_mode: str
    kcal_goal: float | None
    protein_goal: float | None
    fiber_goal: float | None
    dietary_prefs: dict
    conditions: list[str]
    first_meal_time: str | None
    streak_days: int

    model_config = ConfigDict(extra="forbid")


class GoalCreate(BaseModel):
    tracking_mode: TrackingMode = "goals"
    kcal_goal: float | None = Field(default=None, gt=0)
    protein_goal: float | None = Field(default=None, gt=0)
    fiber_goal: float | None = Field(default=None, gt=0)
    dietary_prefs: dict = Field(default_factory=dict)
    conditions: list[Condition] = Field(default_factory=list)
    first_meal_time: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _require_targets_in_goal_mode(self) -> GoalCreate:
        if self.tracking_mode == "goals" and (
            self.kcal_goal is None
            or self.protein_goal is None
            or self.fiber_goal is None
        ):
            raise ValueError(
                "kcal_goal, protein_goal and fiber_goal are required "
                "when tracking_mode is 'goals'"
            )
        return self


class GoalUpdate(BaseModel):
    """PUT body. Omitting ``conditions`` leaves them unchanged; ``[]`` clears."""

    tracking_mode: TrackingMode = "goals"
    kcal_goal: float | None = Field(default=None, gt=0)
    protein_goal: float | None = Field(default=None, gt=0)
    fiber_goal: float | None = Field(default=None, gt=0)
    dietary_prefs: dict = Field(default_factory=dict)
    conditions: list[Condition] | None = None
    first_meal_time: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _require_targets_in_goal_mode(self) -> GoalUpdate:
        if self.tracking_mode == "goals" and (
            self.kcal_goal is None
            or self.protein_goal is None
            or self.fiber_goal is None
        ):
            raise ValueError(
                "kcal_goal, protein_goal and fiber_goal are required "
                "when tracking_mode is 'goals'"
            )
        return self


def _diet_settings(dietary_prefs: dict) -> list[str]:
    """Diet chips switched on in a request; other keys have no home any more."""
    on = [
        profile.normalize_diet_key(key)
        for key, value in dietary_prefs.items()
        if value is True
    ]
    unknown = [key for key in on if key not in profile.DIET_CHIPS]
    if unknown:
        logger.warning("ignoring unknown dietary_prefs keys: %s", unknown)
    return [key for key in on if key in profile.DIET_CHIPS]


async def _to_response(goal: UserGoal) -> GoalResponse:
    """The goals row plus the declarations the profile now owns."""
    entries = await profile.load_hard_profile(goal.user_id)
    return GoalResponse(
        tracking_mode=goal.tracking_mode or "goals",
        kcal_goal=goal.kcal_goal,
        protein_goal=goal.protein_goal,
        fiber_goal=goal.fiber_goal,
        dietary_prefs={s: True for s in profile.active_diet_settings(entries)},
        conditions=[
            c for c in profile.declared_conditions(entries) if c in _CONDITIONS
        ],
        first_meal_time=goal.first_meal_time,
        streak_days=goal.streak_days,
    )


async def _write_declarations(
    user_id: str, conditions: list[str] | None, dietary_prefs: dict
) -> None:
    """Save the Settings choices as confirmed profile entries."""
    try:
        await profile.set_declarations(
            user_id,
            conditions=conditions,
            managed_conditions=_CONDITIONS,
            diet_settings=_diet_settings(dietary_prefs),
        )
    except profile.ProfileFull as exc:
        raise HTTPException(
            status_code=409, detail="The profile is full; remove an entry first"
        ) from exc


@router.get("")
async def get_goals(user_id: str = Depends(get_current_user_id)) -> GoalResponse:
    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="User has not been onboarded")
        return await _to_response(goal)


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
            tracking_mode=req.tracking_mode,
            kcal_goal=req.kcal_goal,
            protein_goal=req.protein_goal,
            fiber_goal=req.fiber_goal,
            first_meal_time=req.first_meal_time,
            streak_days=0,
        )
        session.add(goal)
        await session.commit()
        await session.refresh(goal)
    await _write_declarations(user_id, req.conditions, req.dietary_prefs)
    return await _to_response(goal)


@router.put("")
async def update_goals(
    req: GoalUpdate, user_id: str = Depends(get_current_user_id)
) -> GoalResponse:
    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="User has not been onboarded")

        goal.tracking_mode = req.tracking_mode
        # In mindful mode the client may omit the numeric targets entirely
        # (e.g. the 27-byte "just turn tracking off" request). Keep the
        # previously-set targets on file instead of nulling them out, so
        # switching back to "goals" mode restores the user's own values
        # rather than resetting to generic defaults.
        if req.tracking_mode == "mindful":
            if req.kcal_goal is not None:
                goal.kcal_goal = req.kcal_goal
            if req.protein_goal is not None:
                goal.protein_goal = req.protein_goal
            if req.fiber_goal is not None:
                goal.fiber_goal = req.fiber_goal
        else:
            goal.kcal_goal = req.kcal_goal
            goal.protein_goal = req.protein_goal
            goal.fiber_goal = req.fiber_goal
        goal.first_meal_time = req.first_meal_time
        await session.commit()
        await session.refresh(goal)
    await _write_declarations(user_id, req.conditions, req.dietary_prefs)
    return await _to_response(goal)
