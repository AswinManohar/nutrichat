from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.agent.tools.decompose import normalize_meal_name
from backend.agent.tools.saved_meals import find_saved_meal  # re-exported for callers
from backend.auth.supabase import get_current_user_id
from backend.db.models import UserMeal
from backend.db.session import get_session

__all__ = ["router", "find_saved_meal"]

router = APIRouter(prefix="/my-meals", tags=["my-meals"])

_MACRO_FIELDS = ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g")


class IngredientIn(BaseModel):
    """One resolved ingredient as shown on the confirmation card.

    Extra fields (nutrients, fdc_id, source, estimated, candidates) are kept
    and stored verbatim so a logged-from-saved meal carries full data.
    """

    food_name: str
    qty_g: float = Field(gt=0)
    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0

    model_config = ConfigDict(extra="allow")


class SaveMealRequest(BaseModel):
    name: str = Field(min_length=1)
    ingredients: list[IngredientIn] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class MyMealSummary(BaseModel):
    id: str
    name: str
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    n_ingredients: int

    model_config = ConfigDict(extra="forbid")


class MyMealDetail(MyMealSummary):
    ingredients: list[dict]


def _totals(ingredients: list[IngredientIn]) -> dict[str, float]:
    """Sum macro totals server-side — never trust client-supplied totals."""
    return {f: round(sum(getattr(i, f) for i in ingredients), 2) for f in _MACRO_FIELDS}


def _summary(meal: UserMeal) -> MyMealSummary:
    return MyMealSummary(
        id=meal.id,
        name=meal.name,
        kcal=meal.kcal,
        protein_g=meal.protein_g,
        carbs_g=meal.carbs_g,
        fat_g=meal.fat_g,
        fiber_g=meal.fiber_g,
        n_ingredients=len(meal.ingredients),
    )


@router.get("")
async def list_meals(
    user_id: str = Depends(get_current_user_id),
) -> list[MyMealSummary]:
    async with get_session()() as session:
        stmt = (
            select(UserMeal)
            .where(UserMeal.user_id == user_id, UserMeal.deleted_at.is_(None))
            .order_by(UserMeal.created_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_summary(m) for m in rows]


@router.get("/{meal_id}")
async def get_meal(
    meal_id: str, user_id: str = Depends(get_current_user_id)
) -> MyMealDetail:
    async with get_session()() as session:
        meal = await session.get(UserMeal, meal_id)
        if meal is None or meal.user_id != user_id or meal.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Meal not found")
        base = _summary(meal)
        return MyMealDetail(**base.model_dump(), ingredients=meal.ingredients)


@router.post("", status_code=201)
async def save_meal(
    req: SaveMealRequest, user_id: str = Depends(get_current_user_id)
) -> MyMealDetail:
    normalized = normalize_meal_name(req.name)
    if not normalized:
        raise HTTPException(status_code=422, detail="Meal name is empty")
    totals = _totals(req.ingredients)
    ingredients = [i.model_dump() for i in req.ingredients]

    async with get_session()() as session:
        existing = await session.execute(
            select(UserMeal).where(
                UserMeal.user_id == user_id,
                UserMeal.name_normalized == normalized,
                UserMeal.deleted_at.is_(None),
            )
        )
        if existing.scalars().first() is not None:
            raise HTTPException(
                status_code=409, detail="A meal with that name already exists"
            )

        meal = UserMeal(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=req.name.strip(),
            name_normalized=normalized,
            ingredients=ingredients,
            **totals,
        )
        session.add(meal)
        await session.commit()
        await session.refresh(meal)
        base = _summary(meal)
        return MyMealDetail(**base.model_dump(), ingredients=meal.ingredients)


@router.delete("/{meal_id}", status_code=204)
async def delete_meal(
    meal_id: str, user_id: str = Depends(get_current_user_id)
) -> None:
    from datetime import datetime, timezone

    async with get_session()() as session:
        meal = await session.get(UserMeal, meal_id)
        if meal is None or meal.user_id != user_id or meal.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Meal not found")
        meal.deleted_at = datetime.now(timezone.utc)
        await session.commit()
