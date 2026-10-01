from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.agent.tools.decompose import normalize_meal_name
from backend.agent.tools.meals import MEAL_CATEGORIES, MealLogResult, log_meal
from backend.agent.tools.saved_meals import find_saved_meal  # re-exported for callers
from backend.agent.tools.usda import USDAResult
from backend.auth.supabase import get_current_user_id
from backend.db.models import MealLog, UserMeal
from backend.db.redis_client import current_day_bounds
from backend.db.session import get_session

__all__ = ["router", "find_saved_meal"]

router = APIRouter(prefix="/my-meals", tags=["my-meals"])

_MACRO_FIELDS = ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g")

# Macros scaled per-ingredient when logging a saved meal (superset of
# _MACRO_FIELDS — sugar/sat_fat feed the full USDAResult / nutrient-checkup).
_SCALED_MACROS = (
    "kcal",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sugar_g",
    "sat_fat_g",
)


class IngredientIn(BaseModel):
    """One resolved ingredient as shown on the confirmation card.

    Extra fields (nutrients, fdc_id, source, estimated, candidates) are kept
    and stored verbatim so a logged-from-saved meal carries full data.
    """

    food_name: str
    qty_g: float = Field(gt=0)
    target_qty_g: float | None = Field(default=None, gt=0)
    kcal: float | None = 0.0
    protein_g: float | None = 0.0
    carbs_g: float | None = 0.0
    fat_g: float | None = 0.0
    fiber_g: float | None = 0.0

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
    logged_today: bool = False

    model_config = ConfigDict(extra="forbid")


class MyMealDetail(MyMealSummary):
    ingredients: list[dict]
    updated_at: datetime


def _totals(ingredients: list[dict]) -> dict[str, float]:
    """Sum macro totals server-side; never trust client-supplied totals.

    Args:
        ingredients: Built ingredient dicts. An unknown (None) macro counts as 0.

    Returns:
        Rounded totals keyed by macro field name.
    """
    return {
        f: round(sum((d.get(f) or 0.0) for d in ingredients), 2) for f in _MACRO_FIELDS
    }


def _summary(meal: UserMeal, logged_today: bool = False) -> MyMealSummary:
    return MyMealSummary(
        id=meal.id,
        name=meal.name,
        kcal=meal.kcal,
        protein_g=meal.protein_g,
        carbs_g=meal.carbs_g,
        fat_g=meal.fat_g,
        fiber_g=meal.fiber_g,
        n_ingredients=len(meal.ingredients),
        logged_today=logged_today,
    )


class IngredientOverride(BaseModel):
    """A kept ingredient (by stored index) with its edited gram weight."""

    index: int = Field(ge=0)
    qty_g: float = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class LogMyMealRequest(BaseModel):
    """Log a saved meal. Omit `ingredients` for a 1x quick-log; provide it to
    customize — the listed ingredients are kept (at their qty_g), the rest are
    dropped."""

    meal_type: str
    portion: float = Field(default=1.0, gt=0)
    ingredients: list[IngredientOverride] | None = None

    model_config = ConfigDict(extra="forbid")


def _scaled_macro(stored: dict, macro: str, scale: float) -> float | None:
    """Scale one stored macro, preserving "unknown" (None) instead of zeroing it.

    A macro is unknown when it is null in the stored ingredient, or named in the
    ingredient's `unknown_nutrients` (how the API flags a value FDC lacks while
    still sending legacy clients a numeric 0.0). Ingredients saved before that
    field existed simply carry whatever number they stored.

    kcal is always a number.
    """
    if macro != "kcal":
        if macro in (stored.get("unknown_nutrients") or ()):
            return None
        if macro in stored and stored[macro] is None:
            return None
    return round((stored.get(macro) or 0.0) * scale, 2)


def _scaled_result(stored: dict, edited_qty_g: float, portion: float) -> USDAResult:
    """Rebuild a USDAResult from a stored ingredient, scaled server-side.

    `scale = (edited_qty_g * portion) / stored_qty_g` is applied to qty, the
    promoted macros, and every value in the nested `nutrients` dict. Client
    macros are never trusted — only the gram weight and portion are taken from
    the request.

    Args:
        stored: One saved ingredient dict (meal.ingredients element).
        edited_qty_g: The kept gram weight before the portion multiplier.
        portion: Global portion multiplier (> 0).

    Returns:
        A USDAResult with all nutrition scaled to the new gram weight.
    """
    base_qty = stored.get("qty_g") or 0.0
    new_qty = edited_qty_g * portion
    scale = new_qty / base_qty if base_qty else 0.0

    nutrients: dict = {}
    for name, nv in (stored.get("nutrients") or {}).items():
        if isinstance(nv, dict):
            nutrients[name] = {**nv, "amount": round(nv.get("amount", 0.0) * scale, 4)}
        else:
            nutrients[name] = nv

    return USDAResult(
        fdc_id=stored.get("fdc_id", -1),
        food_name=stored["food_name"],
        qty_g=round(new_qty, 2),
        match_confidence=stored.get("match_confidence", stored.get("confidence", 1.0)),
        candidates=stored.get("candidates", []),
        nutrients=nutrients,
        source=stored.get("source", "USDA"),
        estimated=stored.get("estimated", False),
        **{m: _scaled_macro(stored, m, scale) for m in _SCALED_MACROS},
    )


def _build_ingredients(items: list[IngredientIn], portion: float) -> list[dict]:
    """Scale card ingredients server-side into storable dicts.

    Each item is scaled to `(target_qty_g or qty_g) * portion`. Unknown macros
    stay None; extra card fields pass through. Only explicitly scaled fields
    override the client values.

    Args:
        items: Ingredients as sent by the client.
        portion: Global portion multiplier (> 0).

    Returns:
        One dict per ingredient, ready to store in `user_meal.ingredients`.
    """
    built: list[dict] = []
    for item in items:
        raw = item.model_dump(exclude={"target_qty_g"})
        scaled = _scaled_result(raw, item.target_qty_g or item.qty_g, portion)
        built.append({**raw, **scaled.model_dump(exclude_unset=True)})
    return built


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

        today_start, today_end = current_day_bounds()
        label_result = await session.execute(
            select(MealLog.label).where(
                MealLog.user_id == user_id,
                MealLog.logged_at >= today_start,
                MealLog.logged_at < today_end,
                MealLog.deleted_at.is_(None),
                MealLog.label.isnot(None),
            )
        )
        logged_labels: set[str] = {row.label for row in label_result.all()}

        return [_summary(m, logged_today=m.name in logged_labels) for m in rows]


@router.get("/{meal_id}")
async def get_meal(
    meal_id: str, user_id: str = Depends(get_current_user_id)
) -> MyMealDetail:
    async with get_session()() as session:
        meal = await session.get(UserMeal, meal_id)
        if meal is None or meal.user_id != user_id or meal.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Meal not found")
        base = _summary(meal)
        return MyMealDetail(
            **base.model_dump(),
            ingredients=meal.ingredients,
            updated_at=meal.updated_at,
        )


@router.post("/{meal_id}/log")
async def log_my_meal(
    meal_id: str,
    req: LogMyMealRequest,
    user_id: str = Depends(get_current_user_id),
) -> MealLogResult:
    """Log a saved meal directly (no chat round-trip).

    Quick-log (no `ingredients`) writes the stored meal verbatim at 1x.
    Customize (with `ingredients`) keeps only the listed ingredients, scaled
    by their gram override and the portion multiplier. Reuses `log_meal` so
    flags, Redis today-totals, and the embedding enqueue match chat logging.
    """
    if req.meal_type not in MEAL_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid meal_type")

    async with get_session()() as session:
        meal = await session.get(UserMeal, meal_id)
        if meal is None or meal.user_id != user_id or meal.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Meal not found")
        stored: list[dict] = list(meal.ingredients)
        meal_name = meal.name

    if req.ingredients is None:
        # Quick log — every stored ingredient at its stored gram weight.
        kept = [(s, s.get("qty_g", 0.0)) for s in stored]
    else:
        # Customize — only the listed indices are kept (rest are removed).
        kept = [
            (stored[o.index], o.qty_g)
            for o in req.ingredients
            if 0 <= o.index < len(stored)
        ]
    if not kept:
        raise HTTPException(status_code=422, detail="No ingredients to log")

    results = [_scaled_result(s, qty, req.portion) for s, qty in kept]
    return await log_meal(user_id, results, req.meal_type, label=meal_name)


@router.post("", status_code=201)
async def save_meal(
    req: SaveMealRequest, user_id: str = Depends(get_current_user_id)
) -> MyMealDetail:
    normalized = normalize_meal_name(req.name)
    if not normalized:
        raise HTTPException(status_code=422, detail="Meal name is empty")
    # Stored verbatim (T028 switches this to _build_ingredients).
    ingredients = [i.model_dump(exclude={"target_qty_g"}) for i in req.ingredients]
    totals = _totals(ingredients)

    async with get_session()() as session:
        existing = await session.execute(
            select(UserMeal).where(
                UserMeal.user_id == user_id,
                UserMeal.name_normalized == normalized,
                UserMeal.deleted_at.is_(None),
            )
        )
        if existing.scalars().first() is not None:
            raise HTTPException(status_code=409, detail="name_taken")

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
        return MyMealDetail(
            **base.model_dump(),
            ingredients=meal.ingredients,
            updated_at=meal.updated_at,
        )


@router.delete("/{meal_id}", status_code=204)
async def delete_meal(
    meal_id: str, user_id: str = Depends(get_current_user_id)
) -> None:
    async with get_session()() as session:
        meal = await session.get(UserMeal, meal_id)
        if meal is None or meal.user_id != user_id or meal.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Meal not found")
        meal.deleted_at = datetime.now(UTC)
        await session.commit()
