from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.orchestrator import get_pending_card, handle_message
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
from backend.db.redis_client import (
    _DAY_RESET_HOUR,
    _DAY_TZ,
    current_day_bounds,
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
    client_request_id: str | None = Field(default=None, max_length=64)

    model_config = ConfigDict(extra="forbid")


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
    user_id: str = Depends(get_current_user_id),
) -> MealLogResult:
    """Log a client-provided resolved item set without any LLM round-trip.

    Each item is re-scaled server-side from its own nutrients (never trusting
    client macros beyond the provided gram weight + portion), then persisted
    via the same log_meal path as chat/My-Meals logging so flags, Redis
    today-totals, and the embedding enqueue all match.

    When client_request_id is set, this call is idempotent: a replay (e.g.
    a mobile client retrying after a dropped response) returns the original
    meal with deduplicated=True instead of logging a second time. The
    pre-select below is the fast path; a concurrent replay that loses the
    pre-select race is still caught via the unique index on
    (user_id, client_request_id) and answered the same way.

    Raises:
        HTTPException 422: Invalid meal_type.
    """
    if req.meal_type not in MEAL_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid meal_type")

    if req.client_request_id:
        existing = await _find_by_client_request_id(user_id, req.client_request_id)
        if existing is not None:
            return _dedup_result(existing)

    item_dicts = [it.model_dump() for it in req.items]
    results = [_scaled_result(d, d["target_qty_g"], req.portion) for d in item_dicts]
    label = _meal_label(item_dicts) or None
    try:
        return await persist_meal(
            user_id,
            results,
            req.meal_type,
            label=label,
            client_request_id=req.client_request_id,
        )
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
        return _dedup_result(existing)


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


def _day_bounds_for_date(day: date) -> tuple[datetime, datetime]:
    """Return the nutrition-day [start, end) UTC window for a calendar date.

    ``current_day_bounds`` only derives "today" from the current instant.
    To express an arbitrary past date under the same reset-hour/timezone
    rule, we hand it a synthetic `now` set to exactly `reset_hour` on the
    target local date: since `current_day_bounds` computes
    ``day_date = (now_local - reset_hour).date()``, that construction makes
    `day_date` land exactly on `day` regardless of the configured reset
    hour (0-23).

    Args:
        day: The calendar date (in the configured nutrition-day timezone)
            whose window is requested.

    Returns:
        ``(start_utc, end_utc)`` covering that nutrition day.
    """
    synthetic_now = datetime.combine(day, time(hour=_DAY_RESET_HOUR), tzinfo=_DAY_TZ)
    return current_day_bounds(now=synthetic_now)


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
        current_day_bounds() if date_ is None else _day_bounds_for_date(date_)
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
