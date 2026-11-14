from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeVar

import httpx
import logfire
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from sqlalchemy import func, select
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.agent.intake.history import (
    get_nutrient_checkup_aggregates,
    summarize_nutrient_checkup,
)
from backend.agent.llm import embed_text
from backend.agent.memory.curator import curate_turn
from backend.agent.memory.curator import infer_log_habits as _infer_log_habits
from backend.config import get_tunables
from backend.core.nutrition_day import (
    NUTRITION_DATE_SQL,
    nutrition_today,
    sql_day_params,
)
from backend.db.models import (
    DeviceToken,
    MealLog,
    NutrientCheckup,
    RedFlagEscalation,
    UserGoal,
)
from backend.db.session import dispose_engine, get_session
from backend.observability import configure_observability

_TUNABLES = get_tunables()

celery_app = Celery(
    "nutrichat",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
)

# Interpret crontab schedules in the app's local timezone so the daily
# rollover lines up with the nutrition-day boundary (day.* in tunables.yaml).
celery_app.conf.timezone = _TUNABLES.day.timezone
celery_app.conf.enable_utc = False

celery_app.conf.beat_schedule = {
    "aggregate-daily-summary": {
        "task": "backend.workers.tasks.aggregate_daily_summary",
        "schedule": crontab(hour=1, minute=15),
    },
    "build-nutrient-checkup": {
        "task": "backend.workers.tasks.build_nutrient_checkup",
        "schedule": crontab(hour=1, minute=30),
    },
    "send-daily-summary-telegram": {
        "task": "backend.workers.tasks.send_daily_summary_telegram",
        "schedule": crontab(hour=7, minute=0),
    },
    "build-weekly-summary": {
        "task": "backend.workers.tasks.build_weekly_summary",
        "schedule": crontab(hour=23, minute=0, day_of_week="sun"),
    },
    # After build-weekly-summary, so both read the same finished week.
    "dispatch-log-habits": {
        "task": "backend.workers.tasks.dispatch_log_habits",
        "schedule": crontab(hour=23, minute=20, day_of_week="sun"),
    },
    "send-daily-summary-push": {
        "task": "backend.workers.tasks.send_daily_summary_push",
        "schedule": crontab(hour=7, minute=0),
    },
}


@worker_process_init.connect
def _init_observability(**_: object) -> None:
    """Configure Logfire in each Celery worker process."""
    configure_observability()


# Tunable thresholds — see src/backend/config/tunables.yaml for docs.
_VEG_DAY_FIBER_THRESHOLD_G = _TUNABLES.summaries.veg_day_fiber_threshold_g
_WEAK_SPOT_RATIO = _TUNABLES.summaries.weak_spot_ratio
_MISSED_MEAL_MIN_DAYS = _TUNABLES.summaries.missed_meal_min_days

_WEEKLY_HABITS_MIN_MEALS = _TUNABLES.memory.weekly_habits_min_meals
_STAPLES_WINDOW_DAYS = _TUNABLES.memory.staples_window_days

_MEAL_TYPES = ("breakfast", "lunch", "dinner")


_T = TypeVar("_T")


def _run(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run an async task body in its own loop, then dispose the DB engine.

    Each Celery task gets a fresh event loop via asyncio.run(); the cached
    async engine's connections must be disposed before that loop closes,
    or the next task's loop fails with "Future attached to a different loop".
    """

    async def _wrapped() -> _T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_wrapped())


# ---------------------------------------------------------------------------
# embed_meal_summary
# ---------------------------------------------------------------------------


async def _embed_meal_summary(meal_id: str) -> None:
    session_factory = get_session()
    async with session_factory() as session:
        meal = await session.get(MealLog, meal_id)
        if meal is None:
            return

        label = getattr(meal, "label", None)
        if label:
            body = label
        else:
            body = ", ".join(item["food_name"] for item in meal.entities)
        summary = f"{meal.meal_type}: {body}"
        embedding = await embed_text(summary)

        meal.embedding = embedding
        await session.commit()


@celery_app.task(name="backend.workers.tasks.embed_meal_summary", ignore_result=True)
def embed_meal_summary(meal_id: str) -> None:
    """Embed a meal's food summary and store it on `meal_log.embedding`.

    Args:
        meal_id: UUID of the `meal_log` row to embed.
    """
    _run(_embed_meal_summary(meal_id))


# ---------------------------------------------------------------------------
# extract_and_store_facts
# ---------------------------------------------------------------------------


@celery_app.task(
    name="backend.workers.tasks.extract_and_store_facts", ignore_result=True
)
def extract_and_store_facts(user_id: str, user_input: str, agent_reply: str) -> None:
    """Update the user's profile from one conversation turn.

    One curator call (agent/memory/curator.py) drafts soft and hard facts;
    soft ones can be added, replaced and removed under memory.apply_ops.

    Args:
        user_id: Supabase Auth UUID.
        user_input: The user's message.
        agent_reply: The agent's response.
    """
    _run(curate_turn(user_id, user_input, agent_reply))


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
                "WHERE "
                + NUTRITION_DATE_SQL
                + " = :target_date AND deleted_at IS NULL "
                "GROUP BY user_id"
            ),
            {"target_date": target_date, **sql_day_params()},
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
        else nutrition_today() - timedelta(days=1)
    )
    _run(_aggregate_daily_summary(resolved))


# ---------------------------------------------------------------------------
# dispatch_log_habits / infer_log_habits
# ---------------------------------------------------------------------------


async def _log_habit_candidates() -> list[str]:
    """User ids with enough recent meals for the weekly log-habits job."""
    today = nutrition_today()
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT user_id FROM meal_log "
                "WHERE " + NUTRITION_DATE_SQL + " BETWEEN :date_from AND :date_to "
                "AND deleted_at IS NULL "
                "GROUP BY user_id HAVING COUNT(*) >= :min_meals"
            ),
            {
                "date_from": today - timedelta(days=_STAPLES_WINDOW_DAYS - 1),
                "date_to": today,
                "min_meals": _WEEKLY_HABITS_MIN_MEALS,
                **sql_day_params(),
            },
        )
        return [str(row.user_id) for row in result]


@celery_app.task(name="backend.workers.tasks.dispatch_log_habits", ignore_result=True)
def dispatch_log_habits() -> None:
    """Fan the weekly log-habits job out to one task per eligible user.

    Eligible: at least ``memory.weekly_habits_min_meals`` meals in the last
    ``memory.staples_window_days`` days. One
    query finds them; the per-user work (and its LLM call) runs in
    :func:`infer_log_habits`, so a slow or failing user never blocks the
    rest.
    """
    for user_id in _run(_log_habit_candidates()):
        infer_log_habits.delay(user_id)


# rate_limit is per worker process: it keeps a large fan-out from bursting
# past the Gemini quota.
@celery_app.task(
    name="backend.workers.tasks.infer_log_habits",
    ignore_result=True,
    rate_limit="30/m",
)
def infer_log_habits(user_id: str) -> None:
    """Rewrite one user's log-inferred habit facts.

    Args:
        user_id: Supabase Auth UUID.
    """
    _run(_infer_log_habits(user_id))


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
                "SELECT user_id, meal_type, COUNT(DISTINCT "
                + NUTRITION_DATE_SQL
                + ") AS n_days "
                "FROM meal_log "
                "WHERE " + NUTRITION_DATE_SQL + " BETWEEN :week_start AND :week_end "
                "AND deleted_at IS NULL "
                "GROUP BY user_id, meal_type"
            ),
            {"week_start": week_start, "week_end": week_end, **sql_day_params()},
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
        today = nutrition_today()
        resolved = today - timedelta(days=today.weekday())
    _run(_build_weekly_summary(resolved))


# ---------------------------------------------------------------------------
# build_nutrient_checkup
# ---------------------------------------------------------------------------


async def _build_nutrient_checkup(target_date: date) -> None:
    window_start = target_date - timedelta(days=6)

    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT DISTINCT user_id FROM meal_log "
                "WHERE "
                + NUTRITION_DATE_SQL
                + " BETWEEN :window_start AND :target_date "
                "AND deleted_at IS NULL"
            ),
            {
                "window_start": window_start,
                "target_date": target_date,
                **sql_day_params(),
            },
        )
        user_ids = [row.user_id for row in result.all()]

        for user_id in user_ids:
            nutrients = await get_nutrient_checkup_aggregates(user_id, target_date)
            notable, summary_text = summarize_nutrient_checkup(nutrients)

            stmt = pg_insert(NutrientCheckup).values(
                user_id=user_id,
                date=target_date,
                nutrients=nutrients,
                notable_nutrients=notable,
                summary_text=summary_text,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_={
                    "nutrients": stmt.excluded.nutrients,
                    "notable_nutrients": stmt.excluded.notable_nutrients,
                    "summary_text": stmt.excluded.summary_text,
                    "generated_at": func.now(),
                },
            )
            await session.execute(stmt)
        await session.commit()


@celery_app.task(name="backend.workers.tasks.build_nutrient_checkup")
def build_nutrient_checkup(target_date: str | None = None) -> None:
    """Upsert `nutrient_checkup` rows for every user active in the last 7 days.

    Runs nightly at 01:30 (after aggregate_daily_summary) for the 7-day
    window ending on `target_date`.

    Args:
        target_date: ISO date string for the last day of the window.
            Defaults to yesterday.
    """
    resolved = (
        date.fromisoformat(target_date)
        if target_date
        else nutrition_today() - timedelta(days=1)
    )
    _run(_build_nutrient_checkup(resolved))


# ---------------------------------------------------------------------------
# send_daily_summary_telegram
# ---------------------------------------------------------------------------


async def _send_daily_summary_telegram(target_date: date) -> None:
    # Imported here, not at module level: backend.telegram.bot -> handlers ->
    # agent.orchestrator -> agent.meal_logging.meals -> backend.workers.tasks would
    # otherwise be a circular import at module load time.
    import backend.telegram.bot as telegram_bot

    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT tl.chat_id, nc.user_id, nc.summary_text "
                "FROM nutrient_checkup nc "
                "JOIN telegram_link tl ON tl.user_id = nc.user_id "
                "WHERE nc.date = :target_date "
                "AND nc.summary_text IS NOT NULL "
                "AND nc.telegram_sent_at IS NULL"
            ),
            {"target_date": target_date},
        )
        rows = result.all()

        async with telegram_bot.build_bot() as bot:
            for row in rows:
                await bot.send_message(row.chat_id, row.summary_text)
                await session.execute(
                    sa_text(
                        "UPDATE nutrient_checkup SET telegram_sent_at = now() "
                        "WHERE user_id = :user_id AND date = :target_date"
                    ),
                    {"user_id": row.user_id, "target_date": target_date},
                )
        await session.commit()


@celery_app.task(name="backend.workers.tasks.send_daily_summary_telegram")
def send_daily_summary_telegram(target_date: str | None = None) -> None:
    """Send the daily nutrient summary to linked Telegram chats.

    Runs at 07:00 (after the 01:30 build_nutrient_checkup), for any user
    whose `nutrient_checkup` row for `target_date` has a non-null
    `summary_text` and hasn't been sent yet.

    Args:
        target_date: ISO date string for the check-up date to send.
            Defaults to yesterday (the date build_nutrient_checkup just
            computed).
    """
    resolved = (
        date.fromisoformat(target_date)
        if target_date
        else nutrition_today() - timedelta(days=1)
    )
    _run(_send_daily_summary_telegram(resolved))


# ---------------------------------------------------------------------------
# send_push_fcm / send_daily_summary_push
# ---------------------------------------------------------------------------


@celery_app.task(name="backend.workers.tasks.send_push_fcm")
def send_push_fcm(
    user_id: str, title: str, body: str, data: dict[str, str] | None = None
) -> int:
    """Send an FCM push to every device registered to a user.

    Args:
        user_id: Supabase Auth UUID.
        title: Notification title.
        body: Notification body.
        data: Optional string-keyed payload delivered with the notification.

    Returns:
        Number of tokens the push was successfully sent to.
    """
    from backend.push.fcm import send_to_user

    return _run(send_to_user(user_id, title, body, data))


async def _send_daily_summary_push() -> int:
    session_factory = get_session()
    async with session_factory() as session:
        user_ids = (
            (await session.execute(select(DeviceToken.user_id).distinct()))
            .scalars()
            .all()
        )
    for uid in user_ids:
        send_push_fcm.delay(
            uid,
            "Your Mealsy daily summary",
            "Yesterday's recap is ready — open Mealsy to see it.",
            {"deeplink": "mealsy://chat"},
        )
    return len(user_ids)


@celery_app.task(name="backend.workers.tasks.send_daily_summary_push")
def send_daily_summary_push() -> int:
    """Beat 07:00: enqueue one send_push_fcm per user with device tokens.

    Returns:
        Number of users a push was enqueued for.
    """
    return _run(_send_daily_summary_push())


# ---------------------------------------------------------------------------
# notify_escalation
# ---------------------------------------------------------------------------


async def _notify_escalation(escalation_id: str, attempt: int) -> str:
    """One delivery attempt; returns sent, retry, failed or no_recipient.

    The payload carries ids only: the webhook host is not an approved
    processor for health data (spec 013, R12).
    """
    cfg = _TUNABLES.safety
    async with get_session()() as session:
        row = await session.get(RedFlagEscalation, escalation_id)
        if row is None:
            logfire.error("escalation not found", escalation_id=escalation_id)
            return "failed"
        if row.notify_status == "sent":
            return "sent"
        url = os.environ.get("SAFETY_WEBHOOK_URL")
        if not url:
            row.notify_status = "no_recipient"
            await session.commit()
            logfire.error(
                "red-flag escalation has no recipient: SAFETY_WEBHOOK_URL is unset",
                escalation_id=escalation_id,
                user_id=row.user_id,
            )
            return "no_recipient"
        base = os.environ.get("SAFETY_REVIEW_BASE_URL", "").rstrip("/")
        text = f"Mealsy red flag: {row.rule_label}. Patient {row.user_id}."
        if base:
            text += f" Review: {base}/admin/review/escalations/{row.id}"
        payload = {
            "text": text,
            "escalation_id": row.id,
            "rule_id": row.rule_id,
            "patient_id": row.user_id,
            "created_at": row.created_at.isoformat(),
        }
        failure: str | None = None
        try:
            async with httpx.AsyncClient(
                timeout=cfg.escalation_webhook_timeout_s
            ) as client:
                response = await client.post(url, json=payload)
            if not response.is_success:
                failure = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            # The exception text can embed the (secret) webhook URL.
            failure = type(exc).__name__
        row.notify_attempts = attempt + 1
        if failure is None:
            row.notify_status = "sent"
            row.notified_at = datetime.now(UTC)
            outcome = "sent"
        elif attempt >= len(cfg.escalation_retry_seconds):
            row.notify_status = "failed"
            outcome = "failed"
            logfire.error(
                "red-flag notification failed after the last retry",
                escalation_id=escalation_id,
                user_id=row.user_id,
                failure=failure,
            )
        else:
            outcome = "retry"
        await session.commit()
        return outcome


@celery_app.task(bind=True, name="backend.workers.tasks.notify_escalation")
def notify_escalation(self: Any, escalation_id: str) -> str:
    """POST a red-flag escalation to SAFETY_WEBHOOK_URL, retrying on failure.

    Args:
        escalation_id: ``red_flag_escalation.id``.

    Returns:
        The row's notify status after this attempt (``retry`` when requeued).
    """
    attempt = self.request.retries
    outcome = _run(_notify_escalation(escalation_id, attempt))
    if outcome == "retry":
        raise self.retry(
            countdown=_TUNABLES.safety.escalation_retry_seconds[attempt],
            max_retries=len(_TUNABLES.safety.escalation_retry_seconds),
        )
    return outcome


__all__ = [
    "celery_app",
    "embed_meal_summary",
    "extract_and_store_facts",
    "aggregate_daily_summary",
    "build_weekly_summary",
    "build_nutrient_checkup",
    "send_daily_summary_telegram",
    "send_push_fcm",
    "send_daily_summary_push",
    "notify_escalation",
]
