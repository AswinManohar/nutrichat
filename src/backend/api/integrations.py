"""Read-only integration API for third-party consumers (e.g. life-os).

All endpoints require a service token (`Authorization: Bearer nck_<token>` or
`X-API-Key: nck_<token>`) with the `nutrition:read` scope — see
`backend.auth.integration.get_integration_user`. Paginated endpoints use an
opaque keyset cursor: base64("<updated_at_iso>|<id>"). Soft-deleted meals are
surfaced as tombstones so consumers can reconcile their local cache.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text as sa_text

from backend.auth.integration import get_integration_user
from backend.db.models import UserGoal
from backend.db.session import get_session

router = APIRouter(
    prefix="/v1/integrations",
    tags=["integrations"],
    dependencies=[Depends(get_integration_user)],
)

MAX_LIMIT = 500
DEFAULT_LIMIT = 100
API_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------


def _encode_cursor(updated_at: datetime, row_id: str) -> str:
    """Encode a keyset pagination cursor as base64("<iso>|<id>")."""
    raw = f"{updated_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode an opaque cursor into (updated_at, id).

    Raises:
        HTTPException: 400 if the cursor is malformed.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        iso, row_id = raw.split("|", 1)
        updated_at = datetime.fromisoformat(iso)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    return updated_at, row_id


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class IntegrationMeal(BaseModel):
    """A single meal_log row, or a tombstone if soft-deleted."""

    meal_id: str
    user_id: str | None = None
    logged_at: datetime | None = None
    meal_type: str | None = None
    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    entities: list | None = None
    flags: dict | None = None
    updated_at: datetime
    deleted: bool = False

    model_config = ConfigDict(extra="forbid")


class MealsPage(BaseModel):
    items: list[IntegrationMeal]
    next_cursor: str | None
    has_more: bool

    model_config = ConfigDict(extra="forbid")


class IntegrationDailySummary(BaseModel):
    id: str
    user_id: str
    date: date
    kcal: float
    protein_g: float
    fiber_g: float
    protein_goal_hit: bool
    has_veg_day: bool
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class DailySummaryPage(BaseModel):
    items: list[IntegrationDailySummary]
    next_cursor: str | None
    has_more: bool

    model_config = ConfigDict(extra="forbid")


class IntegrationWeeklySummary(BaseModel):
    id: str
    user_id: str
    week_start: date
    avg_protein_g: float
    days_hit_protein: int
    weak_spots: list[str]
    missed_meals: list[str]
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class WeeklySummaryPage(BaseModel):
    items: list[IntegrationWeeklySummary]
    next_cursor: str | None
    has_more: bool

    model_config = ConfigDict(extra="forbid")


class IntegrationGoals(BaseModel):
    kcal_goal: float
    protein_goal: float
    fiber_goal: float
    dietary_prefs: dict
    streak_days: int

    model_config = ConfigDict(extra="forbid")


class IntegrationHealth(BaseModel):
    status: str
    version: str

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/meals")
async def list_meals(
    since: str | None = Query(default=None, description="Opaque cursor"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user_id: str = Depends(get_integration_user),
) -> MealsPage:
    """List meal_log rows (and tombstones) updated since a cursor.

    Active meals include the full nutrient breakdown, entities, and flags.
    Soft-deleted meals are returned as tombstones — `{meal_id, updated_at,
    deleted: true}` — with no nutrient fields, so consumers can remove them
    from a local cache. Sorted by (updated_at, meal_id) ascending.
    """
    after_updated_at, after_id = (
        _decode_cursor(since) if since else (None, None)
    )

    query = (
        "SELECT meal_id, user_id, logged_at, meal_type, kcal, protein_g, "
        "carbs_g, fat_g, fiber_g, entities, flags, updated_at, deleted_at "
        "FROM meal_log WHERE user_id = :user_id "
    )
    params: dict = {"user_id": user_id, "limit": limit + 1}
    if after_updated_at is not None:
        query += (
            "AND (updated_at, meal_id) > (:after_updated_at, :after_id) "
        )
        params["after_updated_at"] = after_updated_at
        params["after_id"] = after_id
    query += "ORDER BY updated_at ASC, meal_id ASC LIMIT :limit"

    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(sa_text(query), params)
        rows = result.all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = []
    for row in rows:
        if row.deleted_at is not None:
            items.append(
                IntegrationMeal(
                    meal_id=str(row.meal_id),
                    updated_at=row.updated_at,
                    deleted=True,
                )
            )
        else:
            items.append(
                IntegrationMeal(
                    meal_id=str(row.meal_id),
                    user_id=str(row.user_id),
                    logged_at=row.logged_at,
                    meal_type=row.meal_type,
                    kcal=row.kcal,
                    protein_g=row.protein_g,
                    carbs_g=row.carbs_g,
                    fat_g=row.fat_g,
                    fiber_g=row.fiber_g,
                    entities=row.entities,
                    flags=row.flags,
                    updated_at=row.updated_at,
                    deleted=False,
                )
            )

    next_cursor = (
        _encode_cursor(rows[-1].updated_at, rows[-1].meal_id) if rows and has_more else None
    )
    return MealsPage(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get("/daily-summary")
async def list_daily_summary(
    since: str | None = Query(default=None, description="Opaque cursor"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user_id: str = Depends(get_integration_user),
) -> DailySummaryPage:
    """List daily_summary rows updated since a cursor, oldest first."""
    after_updated_at, after_id = (
        _decode_cursor(since) if since else (None, None)
    )

    query = (
        "SELECT id, user_id, date, kcal, protein_g, fiber_g, "
        "protein_goal_hit, has_veg_day, updated_at "
        "FROM daily_summary WHERE user_id = :user_id "
    )
    params: dict = {"user_id": user_id, "limit": limit + 1}
    if after_updated_at is not None:
        query += "AND (updated_at, id) > (:after_updated_at, :after_id) "
        params["after_updated_at"] = after_updated_at
        params["after_id"] = after_id
    query += "ORDER BY updated_at ASC, id ASC LIMIT :limit"

    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(sa_text(query), params)
        rows = result.all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        IntegrationDailySummary(
            id=str(row.id),
            user_id=str(row.user_id),
            date=row.date,
            kcal=row.kcal,
            protein_g=row.protein_g,
            fiber_g=row.fiber_g,
            protein_goal_hit=row.protein_goal_hit,
            has_veg_day=row.has_veg_day,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    next_cursor = (
        _encode_cursor(rows[-1].updated_at, rows[-1].id) if rows and has_more else None
    )
    return DailySummaryPage(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get("/weekly-summary")
async def list_weekly_summary(
    since: str | None = Query(default=None, description="Opaque cursor"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user_id: str = Depends(get_integration_user),
) -> WeeklySummaryPage:
    """List weekly_summary rows updated since a cursor, oldest first."""
    after_updated_at, after_id = (
        _decode_cursor(since) if since else (None, None)
    )

    query = (
        "SELECT id, user_id, week_start, avg_protein_g, days_hit_protein, "
        "weak_spots, missed_meals, updated_at "
        "FROM weekly_summary WHERE user_id = :user_id "
    )
    params: dict = {"user_id": user_id, "limit": limit + 1}
    if after_updated_at is not None:
        query += "AND (updated_at, id) > (:after_updated_at, :after_id) "
        params["after_updated_at"] = after_updated_at
        params["after_id"] = after_id
    query += "ORDER BY updated_at ASC, id ASC LIMIT :limit"

    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(sa_text(query), params)
        rows = result.all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        IntegrationWeeklySummary(
            id=str(row.id),
            user_id=str(row.user_id),
            week_start=row.week_start,
            avg_protein_g=row.avg_protein_g,
            days_hit_protein=row.days_hit_protein,
            weak_spots=list(row.weak_spots or []),
            missed_meals=list(row.missed_meals or []),
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    next_cursor = (
        _encode_cursor(rows[-1].updated_at, rows[-1].id) if rows and has_more else None
    )
    return WeeklySummaryPage(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get("/goals")
async def get_goals(user_id: str = Depends(get_integration_user)) -> IntegrationGoals:
    """Return the user's current nutrition goals and preferences."""
    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="User has not been onboarded")
        return IntegrationGoals(
            kcal_goal=goal.kcal_goal,
            protein_goal=goal.protein_goal,
            fiber_goal=goal.fiber_goal,
            dietary_prefs=goal.dietary_prefs,
            streak_days=goal.streak_days,
        )


@router.get("/health")
async def integration_health() -> IntegrationHealth:
    """Lightweight liveness/version check for the integration API."""
    return IntegrationHealth(status="ok", version=API_VERSION)
