from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.orchestrator import get_pending_card, handle_message, resolve_pending
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
from backend.core.nutrition_day import (
    NUTRITION_DATE_SQL,
    nutrition_today,
    sql_day_params,
)
from backend.db.models import MealLog, UserMeal
from backend.db.redis_client import (
    current_day_bounds,
    day_bounds_for_date,
    get_today_totals,
)
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
        List of dicts with keys meal_type, kcal (float), summary (str),
        n_meals (int, count of meal_log rows of that meal_type today).
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
                "n_meals": 0,
            }
        by_type[meal_type]["kcal"] += float(meal_kcal or 0)
        by_type[meal_type]["n_meals"] += 1

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
    """Log or resume a meal-logging conversation turn.

    The thread id is namespaced with the authenticated user_id
    (`{user_id}:{conversation_id or 'default'}`) so one user can never
    read or resume another user's paused conversation, even if they
    guess or reuse someone else's conversation_id.
    """
    thread_id = f"{user_id}:{req.conversation_id or 'default'}"
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


@router.get("/pending")
async def pending_card(
    request: Request,
    conversation_id: str = Query(min_length=1),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Recover the paused confirmation card for a conversation, if any.

    The thread id is namespaced with the authenticated user_id
    (`{user_id}:{conversation_id}`) so one user can never read another
    user's paused card by passing their conversation_id. Pass
    conversation_id=default to reach the same thread as a POST /meals/log
    call made with no conversation_id.
    """
    thread_id = f"{user_id}:{conversation_id}"
    return await get_pending_card(
        user_id=user_id,
        thread_id=thread_id,
        checkpointer=request.app.state.checkpointer,
    )


class CorrectionIn(BaseModel):
    """A user's correction of one logged item's USDA match (spec 003).

    Sent on the item that was swapped via the food picker. Validated
    against the item's own `fdc_id` by the endpoint (`to_fdc_id` must
    match, 422 otherwise) and written as one `food_correction` row in the
    same transaction as the meal (data-model.md, FR-012).
    """

    original_phrase: str = Field(min_length=1, max_length=200)
    from_fdc_id: int | None = None
    from_name: str = Field(min_length=1, max_length=300)
    to_fdc_id: int
    method: Literal["suggestion", "search"]
    query: str | None = Field(default=None, max_length=200)

    model_config = ConfigDict(extra="forbid")


class LogItemIn(BaseModel):
    """One resolved confirmation-card item to log directly (no LLM).

    `qty_g` is the originally resolved gram weight (the scaling base);
    `target_qty_g` is the user-edited weight before the portion multiplier.
    Extra fields (fdc_id, macros, source, estimated, source_dish) are kept
    verbatim. Any ``nutrients`` / ``micros`` sent are ignored — log_meal
    re-derives micronutrients server-side (spec 008).

    `correction` is optional (spec 003): when set, its `to_fdc_id` must
    equal this item's own `fdc_id` (an extra field kept via `extra="allow"`)
    — the endpoint validates this and returns 422 on a mismatch.
    """

    food_name: str
    qty_g: float = Field(gt=0)
    target_qty_g: float = Field(gt=0)
    correction: CorrectionIn | None = None

    model_config = ConfigDict(extra="allow")


class LogItemsRequest(BaseModel):
    """Log a confirmation card's final item set directly.

    The frontend applies removals and quantity edits locally and sends only
    the kept items; removing or re-weighing an ingredient never calls the LLM.
    A swapped item (spec 003, "Correct a Wrong Food Match") can now also be
    logged this way, via the item's own ``correction`` field, instead of
    round-tripping through chat.
    """

    meal_type: str
    portion: float = Field(default=1.0, gt=0)
    items: list[LogItemIn] = Field(min_length=1)
    client_request_id: str | None = Field(default=None, max_length=64)
    conversation_id: str | None = Field(default=None)
    saved_meal_id: str | None = Field(default=None, max_length=64)

    model_config = ConfigDict(extra="forbid")


async def _owned_saved_meal(user_id: str, saved_meal_id: str) -> UserMeal | None:
    """Return the caller's live saved meal, or None for unknown/foreign/deleted.

    Args:
        user_id: The authenticated user's ID.
        saved_meal_id: Client-supplied saved meal id (untrusted).

    Returns:
        The `UserMeal`, or None when it isn't the caller's or was deleted.
    """
    try:
        async with get_session()() as session:
            result = await session.execute(
                select(UserMeal).where(
                    UserMeal.id == saved_meal_id,
                    UserMeal.user_id == user_id,
                    UserMeal.deleted_at.is_(None),
                )
            )
            return result.scalar_one_or_none()
    except (DBAPIError, ValueError):
        # Malformed (non-UUID) id: treat like unknown, per contract.
        return None


async def _find_by_client_request_id(
    user_id: str, client_request_id: str
) -> MealLog | None:
    """Look up a previously-logged meal by its client idempotency key.

    Args:
        user_id: The authenticated user's ID.
        client_request_id: Client-generated UUID sent with /meals/log-items.

    Returns:
        The matching MealLog row, or None if this request id hasn't been
        seen before for this user.
    """
    session_factory = get_session()
    async with session_factory() as db:
        result = await db.execute(
            select(MealLog).where(
                MealLog.user_id == user_id,
                MealLog.client_request_id == client_request_id,
            )
        )
        return result.scalar_one_or_none()


def _dedup_result(row: MealLog) -> MealLogResult:
    """Rebuild a log_items success response from an already-logged row.

    Used both on the fast path (pre-select finds the row before we try to
    insert) and the race path (insert loses a concurrent-duplicate race and
    we re-select the winner).
    """
    entities = (
        row.entities
        if isinstance(row.entities, list)
        else json.loads(row.entities or "[]")
    )
    return MealLogResult(
        meal_id=row.meal_id,
        meal_type=row.meal_type,
        n_items=len(entities),
        kcal=row.kcal,
        protein_g=row.protein_g,
        carbs_g=row.carbs_g,
        fat_g=row.fat_g,
        fiber_g=row.fiber_g,
        message="Already logged.",
        deduplicated=True,
    )


@router.post("/log-items")
async def log_items(
    req: LogItemsRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> MealLogResult:
    """Log a client-provided resolved item set without any LLM round-trip.

    Each item is re-scaled server-side from its own macros (never trusting
    client macros beyond the provided gram weight + portion), then persisted
    via the same log_meal path as chat/My-Meals logging so flags, Redis
    today-totals, and the embedding enqueue all match. Tracked
    micronutrients sent by the client (``micros`` / ``nutrients``) are never
    stored: log_meal re-derives them from each item's food id (spec 008,
    contracts/meal-micros.md §2), which also keeps "Log again" consistent.

    When client_request_id is set, this call is idempotent: a replay (e.g.
    a mobile client retrying after a dropped response) returns the original
    meal with deduplicated=True instead of logging a second time. The
    pre-select below is the fast path; a concurrent replay that loses the
    pre-select race is still caught via the unique index on
    (user_id, client_request_id) and answered the same way.

    When ``conversation_id`` is set, the paused LangGraph thread that
    produced this card (if any) is marked resolved on every successful
    return path, so `GET /meals/pending` stops returning it (spec 003,
    research R4). Card items may have been swapped locally on the client
    without the graph ever learning about it, so without this a later
    pending-recovery poll could resurrect the stale, unswapped card.

    Raises:
        HTTPException 422: Invalid meal_type, or an item's
            `correction.to_fdc_id` doesn't match its own `fdc_id`.
    """
    if req.meal_type not in MEAL_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid meal_type")

    for item in req.items:
        item_fdc_id = (item.model_extra or {}).get("fdc_id")
        if item.correction is not None and item.correction.to_fdc_id != item_fdc_id:
            raise HTTPException(
                status_code=422,
                detail="correction.to_fdc_id must equal the item's fdc_id",
            )

    if req.client_request_id:
        existing = await _find_by_client_request_id(user_id, req.client_request_id)
        if existing is not None:
            await _resolve_pending_if_any(request, user_id, req.conversation_id)
            return _dedup_result(existing)

    item_dicts = [it.model_dump(exclude={"correction"}) for it in req.items]
    corrections = [
        it.correction.model_dump() if it.correction is not None else None
        for it in req.items
    ]
    results = [_scaled_result(d, d["target_qty_g"], req.portion) for d in item_dicts]
    label = _meal_label(item_dicts) or None
    extra_flags: dict[str, str] | None = None
    if req.saved_meal_id:
        saved = await _owned_saved_meal(user_id, req.saved_meal_id)
        if saved is not None:
            label = saved.name
            extra_flags = {"saved_meal_id": saved.id}
    try:
        result = await persist_meal(
            user_id,
            results,
            req.meal_type,
            label=label,
            client_request_id=req.client_request_id,
            corrections=corrections,
            extra_flags=extra_flags,
        )
        await _resolve_pending_if_any(request, user_id, req.conversation_id)
        return result
    except IntegrityError:
        # Lost the race: another request with the same client_request_id
        # committed between our pre-select and our insert. Re-select the
        # winner and answer as a dedup rather than surfacing the DB error.
        # An IntegrityError with no client_request_id set can't be this
        # race — re-raise rather than looking up a None key.
        if not req.client_request_id:
            raise
        existing = await _find_by_client_request_id(user_id, req.client_request_id)
        if existing is None:
            raise
        await _resolve_pending_if_any(request, user_id, req.conversation_id)
        return _dedup_result(existing)


async def _resolve_pending_if_any(
    request: Request, user_id: str, conversation_id: str | None
) -> None:
    """Mark the paused card for `conversation_id` resolved, if one was sent.

    No-op when the client didn't send a `conversation_id` (older clients,
    or a log-items call with no matching chat thread).

    Args:
        request: The current FastAPI request (for `app.state.checkpointer`).
        user_id: Authenticated Supabase Auth UUID.
        conversation_id: Client-supplied conversation id, or None.
    """
    if not conversation_id:
        return
    thread_id = f"{user_id}:{conversation_id}"
    await resolve_pending(user_id, thread_id, request.app.state.checkpointer)


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
        Dict with kcal, protein_g, carbs_g, fat_g, fiber_g, n_meals, and
        by_type list.
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
    date_from = nutrition_today() - timedelta(days=days - 1)
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT " + NUTRITION_DATE_SQL + " AS day, "
                "COALESCE(SUM(kcal), 0) AS kcal, "
                "COALESCE(SUM(protein_g), 0) AS protein_g, "
                "COALESCE(SUM(carbs_g), 0) AS carbs_g, "
                "COALESCE(SUM(fiber_g), 0) AS fiber_g, "
                "COUNT(*) AS n_meals, "
                "COUNT(*) FILTER (WHERE (flags->>'has_junk')::boolean) AS junk_meals "
                "FROM meal_log "
                "WHERE user_id = :user_id AND " + NUTRITION_DATE_SQL + " >= :date_from "
                "AND deleted_at IS NULL "
                "GROUP BY day ORDER BY day"
            ),
            {"user_id": user_id, "date_from": date_from, **sql_day_params()},
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


class MealLogSummary(BaseModel):
    """Summary of one logged meal, for the logged-meal list view."""

    meal_id: str
    meal_type: str
    logged_at: datetime
    label: str | None
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    n_items: int

    model_config = ConfigDict(extra="forbid")


class MealLogDetail(MealLogSummary):
    """Full detail of one logged meal, including its resolved items."""

    items: list[dict]

    model_config = ConfigDict(extra="forbid")


def _entities_list(entities_raw: list | str | None) -> list:
    """Normalize a MealLog.entities value to a list.

    The JSONB column is usually deserialized to a list already, but some
    paths (see _get_today_by_type) store or return it as a JSON string.

    Args:
        entities_raw: The raw value read from MealLog.entities.

    Returns:
        The parsed list of item dicts, or [] if entities_raw is falsy.
    """
    return (
        entities_raw
        if isinstance(entities_raw, list)
        else json.loads(entities_raw or "[]")
    )


@router.get("/log")
async def list_meal_logs(
    date_: date | None = Query(default=None, alias="date"),
    meal_type: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
) -> list[MealLogSummary]:
    """List the authenticated user's logged meals for a single day.

    Args:
        date_: Calendar date to list, in the configured nutrition-day
            timezone. Defaults to today (same nutrition-day window used by
            GET /meals/today) when omitted.
        meal_type: Optional filter to a single meal category.
        user_id: Injected by the Supabase auth dependency.

    Returns:
        Meals owned by the caller, not soft-deleted, within the requested
        nutrition-day window, ordered by logged_at ascending.

    Raises:
        HTTPException 422: If meal_type is not a recognized category.
    """
    if meal_type is not None and meal_type not in MEAL_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid meal_type")

    day_start, day_end = (
        current_day_bounds() if date_ is None else day_bounds_for_date(date_)
    )

    filters = [
        MealLog.user_id == user_id,
        MealLog.logged_at >= day_start,
        MealLog.logged_at < day_end,
        MealLog.deleted_at.is_(None),
    ]
    if meal_type is not None:
        filters.append(MealLog.meal_type == meal_type)

    session_factory = get_session()
    async with session_factory() as db:
        result = await db.execute(
            select(MealLog).where(*filters).order_by(MealLog.logged_at.asc())
        )
        rows = result.scalars().all()

    return [
        MealLogSummary(
            meal_id=row.meal_id,
            meal_type=row.meal_type,
            logged_at=row.logged_at,
            label=row.label,
            kcal=row.kcal,
            protein_g=row.protein_g,
            carbs_g=row.carbs_g,
            fat_g=row.fat_g,
            fiber_g=row.fiber_g,
            n_items=len(_entities_list(row.entities)),
        )
        for row in rows
    ]


@router.get("/log/{meal_id}")
async def get_meal_log(
    meal_id: str,
    user_id: str = Depends(get_current_user_id),
) -> MealLogDetail:
    """Return full detail, including resolved items, for one logged meal.

    Args:
        meal_id: The meal_log row's id.
        user_id: Injected by the Supabase auth dependency.

    Returns:
        The meal's summary fields plus its verbatim resolved item list.

    Raises:
        HTTPException 404: If no matching, non-deleted meal owned by this
            user exists. The same 404 covers "doesn't exist", "belongs to
            another user", and "soft-deleted", so existence is never leaked.
    """
    session_factory = get_session()
    async with session_factory() as db:
        result = await db.execute(
            select(MealLog).where(
                MealLog.meal_id == meal_id,
                MealLog.user_id == user_id,
                MealLog.deleted_at.is_(None),
            )
        )
        row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Meal not found")

    entities = _entities_list(row.entities)
    return MealLogDetail(
        meal_id=row.meal_id,
        meal_type=row.meal_type,
        logged_at=row.logged_at,
        label=row.label,
        kcal=row.kcal,
        protein_g=row.protein_g,
        carbs_g=row.carbs_g,
        fat_g=row.fat_g,
        fiber_g=row.fiber_g,
        n_items=len(entities),
        items=entities,
    )
