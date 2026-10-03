from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, Self

from fastapi import APIRouter, Depends, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.agent.tools.decompose import normalize_meal_name
from backend.agent.tools.meals import MEAL_CATEGORIES, MealLogResult, log_meal
from backend.agent.tools.replace_ingredient import (
    QuotaExhausted,
    RephraseRequired,
    ReplacingIngredient,
    ResolveUnavailable,
    resolve_ingredient,
)
from backend.agent.tools.saved_meals import find_saved_meal  # re-exported for callers
from backend.agent.tools.usda import USDAResult
from backend.auth.supabase import get_current_user_id
from backend.db.models import MealLog, UserMeal
from backend.db.redis_client import current_day_bounds
from backend.db.session import get_session
from backend.quota import UPGRADE_MSG
from backend.ratelimit import user_rate_limiter

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
    portion: float = Field(default=1.0, gt=0)

    model_config = ConfigDict(extra="forbid")


class UpdateMealRequest(BaseModel):
    """Replace a saved meal's name and ingredients (optimistic concurrency)."""

    name: str = Field(min_length=1, max_length=120)
    expected_updated_at: datetime
    ingredients: list[IngredientIn] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("expected_updated_at")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        """Reject naive datetimes: they cannot be compared to timestamptz."""
        if value.tzinfo is None:
            raise ValueError("expected_updated_at must include a timezone")
        return value


class ResolveIngredientRequest(BaseModel):
    """Free-text ingredient edit for the saved-meal editor."""

    mode: Literal["swap", "add"]
    text: str = Field(min_length=1, max_length=200)
    meal_name: str = Field(min_length=1, max_length=120)
    replacing: ReplacingIngredient | None = None

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_replacing(self) -> Self:
        """`replacing` is required for swap and must be absent for add."""
        if self.mode == "swap" and self.replacing is None:
            raise ValueError("replacing is required when mode is swap")
        if self.mode == "add" and self.replacing is not None:
            raise ValueError("replacing must be absent when mode is add")
        return self


class ResolveIngredientResponse(BaseModel):
    item: USDAResult
    unit: str
    amount_stated: bool
    kept_previous_qty: bool


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
            select(
                MealLog.label,
                MealLog.flags["saved_meal_id"].astext.label("saved_meal_id"),
            ).where(
                MealLog.user_id == user_id,
                MealLog.logged_at >= today_start,
                MealLog.logged_at < today_end,
                MealLog.deleted_at.is_(None),
            )
        )
        log_rows = label_result.all()
        logged_labels: set[str] = {r.label for r in log_rows if r.label is not None}
        logged_ids: set[str] = {
            r.saved_meal_id for r in log_rows if r.saved_meal_id is not None
        }

        # Match by the saved_meal_id flag (survives renames) or, for legacy
        # logs without the flag, by label.
        return [
            _summary(m, logged_today=m.id in logged_ids or m.name in logged_labels)
            for m in rows
        ]


@router.post(
    "/resolve-ingredient",
    dependencies=[
        Depends(user_rate_limiter("resolve_ingredient", limit=20, window_s=60))
    ],
)
async def resolve_ingredient_route(
    req: ResolveIngredientRequest,
    user_id: str = Depends(get_current_user_id),
) -> ResolveIngredientResponse:
    """Turn free text into one card item for the editor (costs 1 credit).

    Stateless: never changes a saved meal; the editor saves through PUT.
    """
    try:
        resolved = await resolve_ingredient(
            user_id, req.mode, req.text, req.meal_name, req.replacing
        )
    except QuotaExhausted:
        raise HTTPException(
            status_code=402,
            detail={"code": "quota_exhausted", "message": UPGRADE_MSG},
        ) from None
    except RephraseRequired:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "rephrase",
                "message": "Describe one food, e.g. 'brown rice' or '1 tbsp ghee'.",
            },
        ) from None
    except ResolveUnavailable:
        raise HTTPException(
            status_code=503, detail={"code": "resolve_unavailable"}
        ) from None
    return ResolveIngredientResponse(
        item=resolved.item,
        unit=resolved.unit,
        amount_stated=resolved.amount_stated,
        kept_previous_qty=resolved.kept_previous_qty,
    )


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

    Tracked micronutrients are re-derived server-side by log_meal from each
    ingredient's food id; stored or client values are never trusted (spec
    008 research R9).

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
    return await log_meal(
        user_id,
        results,
        req.meal_type,
        label=meal_name,
        extra_flags={"saved_meal_id": meal_id},
    )


@router.post("", status_code=201)
async def save_meal(
    req: SaveMealRequest, user_id: str = Depends(get_current_user_id)
) -> MyMealDetail:
    normalized = normalize_meal_name(req.name)
    if not normalized:
        raise HTTPException(status_code=422, detail="Meal name is empty")
    ingredients = _build_ingredients(req.ingredients, req.portion)
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


@router.put("/{meal_id}")
async def update_meal(
    meal_id: str,
    req: UpdateMealRequest,
    user_id: str = Depends(get_current_user_id),
) -> MyMealDetail:
    """Replace a saved meal's name and ingredients.

    Totals are recomputed server-side from the scaled ingredients. A stale
    `expected_updated_at` yields 409 `meal_changed` with the current meal;
    a clash with another live meal's name yields 409 `name_taken`. Never
    touches `meal_log`, so past logs keep their original values.
    """
    normalized = normalize_meal_name(req.name)
    if not normalized:
        raise HTTPException(status_code=422, detail="Meal name is empty")

    async with get_session()() as session:
        found = await session.execute(
            select(UserMeal).where(UserMeal.id == meal_id).with_for_update()
        )
        meal = found.scalars().first()
        if meal is None or meal.user_id != user_id or meal.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Meal not found")

        if meal.updated_at != req.expected_updated_at:
            current = MyMealDetail(
                **_summary(meal).model_dump(),
                ingredients=meal.ingredients,
                updated_at=meal.updated_at,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "meal_changed",
                    "current": current.model_dump(mode="json"),
                },
            )

        clash = await session.execute(
            select(UserMeal.id).where(
                UserMeal.user_id == user_id,
                UserMeal.name_normalized == normalized,
                UserMeal.deleted_at.is_(None),
                UserMeal.id != meal_id,
            )
        )
        if clash.scalars().first() is not None:
            raise HTTPException(status_code=409, detail="name_taken")

        ingredients = _build_ingredients(req.ingredients, 1.0)
        meal.name = req.name.strip()
        meal.name_normalized = normalized
        meal.ingredients = ingredients
        for field, value in _totals(ingredients).items():
            setattr(meal, field, value)
        # Explicit so the optimistic-concurrency token always moves.
        meal.updated_at = datetime.now(UTC)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=409, detail="name_taken") from None
        await session.refresh(meal)
        return MyMealDetail(
            **_summary(meal).model_dump(),
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
