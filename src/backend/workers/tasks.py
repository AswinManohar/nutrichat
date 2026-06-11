from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from datetime import date, timedelta
from typing import Any

from celery import Celery
from celery.schedules import crontab
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy import text as sa_text

from backend.agent.llm import FLASH_LITE_MODEL, embed_text, make_llm
from backend.config import get_tunables
from backend.db.models import MealLog, UserGoal, UserMemory
from backend.db.redis_client import reset_day_key
from backend.db.session import dispose_engine, get_session

_TUNABLES = get_tunables()

celery_app = Celery(
    "nutrichat",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
)

celery_app.conf.beat_schedule = {
    "reset-day-keys": {
        "task": "backend.workers.tasks.reset_day_keys",
        "schedule": crontab(hour=0, minute=0),
    },
    "aggregate-daily-summary": {
        "task": "backend.workers.tasks.aggregate_daily_summary",
        "schedule": crontab(hour=0, minute=5),
    },
    "build-weekly-summary": {
        "task": "backend.workers.tasks.build_weekly_summary",
        "schedule": crontab(hour=23, minute=0, day_of_week="sun"),
    },
}

# Tunable thresholds — see src/backend/config/tunables.yaml for docs.
_DEDUP_DISTANCE_THRESHOLD = _TUNABLES.memory.dedup_distance_threshold
_NEW_FACT_CONFIDENCE = _TUNABLES.memory.new_fact_confidence
_VEG_DAY_FIBER_THRESHOLD_G = _TUNABLES.summaries.veg_day_fiber_threshold_g
_WEAK_SPOT_RATIO = _TUNABLES.summaries.weak_spot_ratio
_MISSED_MEAL_MIN_DAYS = _TUNABLES.summaries.missed_meal_min_days

_MEAL_TYPES = ("breakfast", "lunch", "dinner")


def _run(coro: Coroutine[Any, Any, None]) -> None:
    """Run an async task body in its own loop, then dispose the DB engine.

    Each Celery task gets a fresh event loop via asyncio.run(); the cached
    async engine's connections must be disposed before that loop closes,
    or the next task's loop fails with "Future attached to a different loop".
    """

    async def _wrapped() -> None:
        try:
            await coro
        finally:
            await dispose_engine()

    asyncio.run(_wrapped())


class _ExtractedFacts(BaseModel):
    """Preference/habit facts extracted from a conversation turn."""

    facts: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


_FACT_EXTRACTION_SYSTEM = _TUNABLES.prompts.fact_extraction_system

_fact_extraction_llm = make_llm(FLASH_LITE_MODEL).with_structured_output(
    _ExtractedFacts
)


# ---------------------------------------------------------------------------
# embed_meal_summary
# ---------------------------------------------------------------------------


async def _embed_meal_summary(meal_id: str) -> None:
    session_factory = get_session()
    async with session_factory() as session:
        meal = await session.get(MealLog, meal_id)
        if meal is None:
            return

        food_names = [item["food_name"] for item in meal.entities]
        summary = f"{meal.meal_type}: " + ", ".join(food_names)
        embedding = await embed_text(summary)

        meal.embedding = embedding
        await session.commit()


@celery_app.task(name="backend.workers.tasks.embed_meal_summary")
def embed_meal_summary(meal_id: str) -> None:
    """Embed a meal's food summary and store it on `meal_log.embedding`.

    Args:
        meal_id: UUID of the `meal_log` row to embed.
    """
    _run(_embed_meal_summary(meal_id))


# ---------------------------------------------------------------------------
# extract_and_store_facts
# ---------------------------------------------------------------------------


async def _extract_and_store_facts(
    user_id: str, user_input: str, agent_reply: str
) -> None:
    extracted = await _fact_extraction_llm.ainvoke(
        [
            SystemMessage(content=_FACT_EXTRACTION_SYSTEM),
            HumanMessage(content=f"User: {user_input}\nAssistant: {agent_reply}"),
        ]
    )
    if not extracted.facts:
        return

    session_factory = get_session()
    async with session_factory() as session:
        for fact in extracted.facts:
            embedding = await embed_text(fact)

            stmt = (
                select(
                    UserMemory.id,
                    UserMemory.embedding.cosine_distance(embedding).label("distance"),
                )
                .where(UserMemory.user_id == user_id)
                .order_by("distance")
                .limit(1)
            )
            nearest = (await session.execute(stmt)).first()
            if nearest is not None and nearest.distance < _DEDUP_DISTANCE_THRESHOLD:
                continue

            session.add(
                UserMemory(
                    user_id=user_id,
                    fact=fact,
                    embedding=embedding,
                    category="preference",
                    confidence=_NEW_FACT_CONFIDENCE,
                )
            )
        await session.commit()


@celery_app.task(name="backend.workers.tasks.extract_and_store_facts")
def extract_and_store_facts(user_id: str, user_input: str, agent_reply: str) -> None:
    """Extract lasting preference facts from a conversation turn and store them.

    Deduplicates against existing `user_memory` rows by cosine distance.

    Args:
        user_id: Supabase Auth UUID.
        user_input: The user's message.
        agent_reply: The agent's response.
    """
    _run(_extract_and_store_facts(user_id, user_input, agent_reply))


# ---------------------------------------------------------------------------
# aggregate_daily_summary
# ---------------------------------------------------------------------------


async def _aggregate_daily_summary(target_date: date) -> None:
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT user_id, "
                "COALESCE(SUM(kcal), 0) AS kcal, "
                "COALESCE(SUM(protein_g), 0) AS protein_g, "
                "COALESCE(SUM(fiber_g), 0) AS fiber_g "
                "FROM meal_log "
                "WHERE logged_at::date = :target_date "
                "GROUP BY user_id"
            ),
            {"target_date": target_date},
        )
        rows = result.all()

        for row in rows:
            goal = await session.get(UserGoal, row.user_id)
            protein_goal_hit = goal is not None and row.protein_g >= goal.protein_goal
            has_veg_day = row.fiber_g >= _VEG_DAY_FIBER_THRESHOLD_G

            await session.execute(
                sa_text(
                    "INSERT INTO daily_summary "
                    "(user_id, date, kcal, protein_g, fiber_g, "
                    "protein_goal_hit, has_veg_day) "
                    "VALUES (:user_id, :date, :kcal, :protein_g, :fiber_g, "
                    ":protein_goal_hit, :has_veg_day) "
                    "ON CONFLICT (user_id, date) DO UPDATE SET "
                    "kcal = EXCLUDED.kcal, "
                    "protein_g = EXCLUDED.protein_g, "
                    "fiber_g = EXCLUDED.fiber_g, "
                    "protein_goal_hit = EXCLUDED.protein_goal_hit, "
                    "has_veg_day = EXCLUDED.has_veg_day"
                ),
                {
                    "user_id": row.user_id,
                    "date": target_date,
                    "kcal": float(row.kcal),
                    "protein_g": float(row.protein_g),
                    "fiber_g": float(row.fiber_g),
                    "protein_goal_hit": protein_goal_hit,
                    "has_veg_day": has_veg_day,
                },
            )
        await session.commit()


@celery_app.task(name="backend.workers.tasks.aggregate_daily_summary")
def aggregate_daily_summary(target_date: str | None = None) -> None:
    """Upsert `daily_summary` rows for every user with meals on a given date.

    Runs nightly at 00:05 for the day that just ended.

    Args:
        target_date: ISO date string to aggregate. Defaults to yesterday.
    """
    resolved = (
        date.fromisoformat(target_date)
        if target_date
        else date.today() - timedelta(days=1)
    )
    _run(_aggregate_daily_summary(resolved))


# ---------------------------------------------------------------------------
# build_weekly_summary
# ---------------------------------------------------------------------------


async def _build_weekly_summary(week_start: date) -> None:
    week_end = week_start + timedelta(days=6)

    session_factory = get_session()
    async with session_factory() as session:
        daily_result = await session.execute(
            sa_text(
                "SELECT user_id, "
                "AVG(protein_g) AS avg_protein_g, "
                "AVG(fiber_g) AS avg_fiber_g, "
                "SUM(protein_goal_hit::int) AS days_hit_protein "
                "FROM daily_summary "
                "WHERE date BETWEEN :week_start AND :week_end "
                "GROUP BY user_id"
            ),
            {"week_start": week_start, "week_end": week_end},
        )
        daily_rows = daily_result.all()

        meal_type_result = await session.execute(
            sa_text(
                "SELECT user_id, meal_type, COUNT(DISTINCT logged_at::date) AS n_days "
                "FROM meal_log "
                "WHERE logged_at::date BETWEEN :week_start AND :week_end "
                "GROUP BY user_id, meal_type"
            ),
            {"week_start": week_start, "week_end": week_end},
        )
        meal_days: dict[str, dict[str, int]] = {}
        for row in meal_type_result.all():
            meal_days.setdefault(row.user_id, {})[row.meal_type] = row.n_days

        for row in daily_rows:
            goal = await session.get(UserGoal, row.user_id)

            weak_spots = []
            if row.days_hit_protein < _MISSED_MEAL_MIN_DAYS:
                weak_spots.append("protein")
            if (
                goal is not None
                and row.avg_fiber_g < goal.fiber_goal * _WEAK_SPOT_RATIO
            ):
                weak_spots.append("fiber")

            user_meal_days = meal_days.get(row.user_id, {})
            missed_meals = [
                meal_type
                for meal_type in _MEAL_TYPES
                if user_meal_days.get(meal_type, 0) < _MISSED_MEAL_MIN_DAYS
            ]

            await session.execute(
                sa_text(
                    "INSERT INTO weekly_summary "
                    "(user_id, week_start, avg_protein_g, days_hit_protein, "
                    "weak_spots, missed_meals) "
                    "VALUES (:user_id, :week_start, :avg_protein_g, :days_hit_protein, "
                    ":weak_spots, :missed_meals) "
                    "ON CONFLICT (user_id, week_start) DO UPDATE SET "
                    "avg_protein_g = EXCLUDED.avg_protein_g, "
                    "days_hit_protein = EXCLUDED.days_hit_protein, "
                    "weak_spots = EXCLUDED.weak_spots, "
                    "missed_meals = EXCLUDED.missed_meals"
                ),
                {
                    "user_id": row.user_id,
                    "week_start": week_start,
                    "avg_protein_g": float(row.avg_protein_g),
                    "days_hit_protein": int(row.days_hit_protein),
                    "weak_spots": weak_spots,
                    "missed_meals": missed_meals,
                },
            )
        await session.commit()


@celery_app.task(name="backend.workers.tasks.build_weekly_summary")
def build_weekly_summary(week_start: str | None = None) -> None:
    """Aggregate the past week's `daily_summary` rows into `weekly_summary`.

    Runs Sunday at 23:00 for the week that's about to end (Monday-Sunday).

    Args:
        week_start: ISO date string for the Monday of the week to summarize.
            Defaults to the Monday of the current week.
    """
    if week_start:
        resolved = date.fromisoformat(week_start)
    else:
        today = date.today()
        resolved = today - timedelta(days=today.weekday())
    _run(_build_weekly_summary(resolved))


# ---------------------------------------------------------------------------
# reset_day_keys
# ---------------------------------------------------------------------------


async def _reset_day_keys() -> None:
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(select(UserGoal.user_id))
        user_ids = result.scalars().all()

    for user_id in user_ids:
        await reset_day_key(user_id)


@celery_app.task(name="backend.workers.tasks.reset_day_keys")
def reset_day_keys() -> None:
    """Clear every user's Redis daily-totals key at midnight."""
    _run(_reset_day_keys())


__all__ = [
    "celery_app",
    "embed_meal_summary",
    "extract_and_store_facts",
    "aggregate_daily_summary",
    "build_weekly_summary",
    "reset_day_keys",
]
