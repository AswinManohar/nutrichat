"""Three weeks of meals: what the coach suggested and what the patient ate.

One bounded read feeds two consumers: the recipe prompt (variety, FR-026) and
``GET /profile/meals`` (the patient's own view, FR-028). Suggested meals come
from ``recommendation`` rows (name, status, rejection reason); eaten meals are
the ``meal_log`` labels. Nothing is stored twice: both are read as they are.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.agent.memory import normalize_fact
from backend.config import get_tunables
from backend.db.models import MealLog, Recommendation
from backend.db.session import get_session

logger = logging.getLogger(__name__)

_MEMORY = get_tunables().memory

_HEADER = "Meals from the last {days} days (do not repeat these without being asked):"


class SuggestedMeal(BaseModel):
    """A recipe the coach showed, with the patient's reaction."""

    recommendation_id: str
    name: str
    status: str
    rejection_reason: str | None
    created_at: datetime

    model_config = ConfigDict(extra="forbid")


class EatenMeal(BaseModel):
    """A logged meal, by its label."""

    label: str
    logged_at: datetime

    model_config = ConfigDict(extra="forbid")


async def load_suggested(
    user_id: str, days: int, limit: int | None = None
) -> list[SuggestedMeal]:
    """Recipes shown in the last ``days`` days, newest first.

    Args:
        user_id: Supabase Auth UUID.
        days: Window length.
        limit: Most rows to read; None reads the whole window.

    Returns:
        The shown, accepted and rejected recommendations.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(
            Recommendation.id,
            Recommendation.recipe["name"].astext.label("name"),
            Recommendation.status,
            Recommendation.rejection_reason,
            Recommendation.created_at,
        )
        .where(Recommendation.user_id == user_id, Recommendation.created_at >= since)
        .order_by(Recommendation.created_at.desc())
        .limit(limit)
    )
    async with get_session()() as session:
        rows = (await session.execute(stmt)).all()
    return [
        SuggestedMeal(
            recommendation_id=str(r.id),
            name=r.name or "A recipe",
            status=r.status,
            rejection_reason=r.rejection_reason,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def load_eaten(
    user_id: str, days: int, limit: int | None = None
) -> list[EatenMeal]:
    """Labelled meals logged in the last ``days`` days, newest first.

    Args:
        user_id: Supabase Auth UUID.
        days: Window length.
        limit: Most rows to read; None reads the whole window.

    Returns:
        One item per logged meal that has a label.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(MealLog.label, MealLog.logged_at)
        .where(
            MealLog.user_id == user_id,
            MealLog.deleted_at.is_(None),
            MealLog.label.is_not(None),
            MealLog.logged_at >= since,
        )
        .order_by(MealLog.logged_at.desc())
        .limit(limit)
    )
    async with get_session()() as session:
        rows = (await session.execute(stmt)).all()
    return [EatenMeal(label=r.label, logged_at=r.logged_at) for r in rows]


def render_history_block(
    suggested: list[SuggestedMeal],
    eaten: list[EatenMeal],
    *,
    days: int,
    max_lines: int,
) -> str:
    """Render suggested and eaten meals as a short, de-duplicated prompt block.

    A meal appears once, under the first status that names it: suggested
    meals (newest first) before logged ones, so a rejection and its reason are
    never hidden by a later log of the same dish.

    Args:
        suggested: Recipes shown, newest first.
        eaten: Logged meals, newest first.
        days: Window length, for the heading.
        max_lines: Most meal lines to keep.

    Returns:
        The block, or "" when there is nothing to say.
    """
    seen: set[str] = set()
    lines: list[str] = []
    for meal in suggested:
        key = normalize_fact(meal.name)
        if key in seen:
            continue
        seen.add(key)
        note = f"suggested, {meal.status}"
        if meal.rejection_reason:
            note += f": {meal.rejection_reason}"
        lines.append(f"- {meal.name} ({note})")
    for meal in eaten:
        key = normalize_fact(meal.label)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {meal.label} (eaten)")
    if not lines:
        return ""
    return "\n".join([_HEADER.format(days=days), *lines[:max_lines]])


async def build_history_block(user_id: str) -> str:
    """The last three weeks of meals as a prompt block; "" when unavailable.

    Soft context is an enrichment (FR-027): a failed read is logged and the
    request goes on with the hard profile alone. Both reads run in parallel
    and are bounded by ``memory.history_max_lines`` rows each.

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        The rendered block, or "" when there is no history or it failed.
    """
    days = _MEMORY.history_days
    max_lines = _MEMORY.history_max_lines
    try:
        suggested, eaten = await asyncio.gather(
            load_suggested(user_id, days, max_lines),
            load_eaten(user_id, days, max_lines),
        )
    except Exception as exc:  # noqa: BLE001 - enrichment must not fail the request
        logger.warning("meal history unavailable for %s: %s", user_id, exc)
        return ""
    return render_history_block(suggested, eaten, days=days, max_lines=max_lines)
