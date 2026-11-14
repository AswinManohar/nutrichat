from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.agent.intake.history import get_staple_foods
from backend.agent.intake.mindful import (
    SafetyAlert,
    evaluate_safety,
    get_daily_intake,
)
from backend.agent.memory.facts import (
    MemoryFact,
    load_profile,
    render_profile_block,
)
from backend.config import get_tunables
from backend.core.nutrition_day import nutrition_today
from backend.db.models import UserGoal, WeeklySummary
from backend.db.redis_client import (
    TodayTotals,
    get_cached_staples,
    get_today_totals,
    set_cached_staples,
)
from backend.db.session import get_session
from backend.safety import profile as hard_profile
from backend.safety.profile import HardEntry
from backend.safety.tables import load_tables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()


class GoalSummary(BaseModel):
    """User's nutrition goals/mode, as read from `user_goal`.

    In mindful mode the three target fields are None and `active_alerts`
    carries any UL safety breaches for today.
    """

    tracking_mode: str = "goals"
    kcal_goal: float | None = None
    protein_goal: float | None = None
    fiber_goal: float | None = None
    streak_days: int
    active_alerts: list[SafetyAlert] = []

    model_config = ConfigDict(extra="forbid")


class WeeklyPattern(BaseModel):
    """Most recent weekly summary, if one has been computed yet."""

    avg_protein_g: float
    days_hit_protein: int
    weak_spots: list[str]
    missed_meals: list[str]

    model_config = ConfigDict(extra="forbid")


class ContextBundle(BaseModel):
    """Everything build_system_prompt needs to assemble the coaching prompt.

    Assembled by build_context() from Redis (today totals), Postgres
    (goals + weekly pattern), and the user's soft profile: every live fact
    plus staple foods from their logs.
    """

    today_totals: TodayTotals
    goals: GoalSummary | None = None
    weekly_pattern: WeeklyPattern | None = None
    hard_block: str = ""
    profile: list[MemoryFact] = []
    staples: dict[str, list[str]] = {}

    model_config = ConfigDict(extra="forbid")


async def _load_soft_profile(user_id: str) -> list[MemoryFact]:
    """The user's soft facts; none when they cannot be read.

    Soft preferences enrich the prompt (FR-027), so a failed read is logged
    and the turn goes on with the hard profile alone.
    """
    try:
        return await load_profile(user_id)
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("soft profile unavailable for %s: %s", user_id, exc)
        return []


async def fetch_staples(user_id: str) -> dict[str, list[str]]:
    """Staple foods from the Redis cache, falling back to Postgres.

    The staples line is a soft enrichment, so any failure degrades to no
    staples rather than failing the context build.
    """
    cached = await get_cached_staples(user_id)
    if cached is not None:
        return cached
    try:
        staples = await get_staple_foods(user_id)
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("staples query failed for %s: %s", user_id, exc)
        return {}
    await set_cached_staples(user_id, staples)
    return staples


def _goal_summary(goal_row: UserGoal | None) -> GoalSummary | None:
    """The coach's view of a ``user_goal`` row (None when the user has none)."""
    if goal_row is None:
        return None
    return GoalSummary(
        tracking_mode=goal_row.tracking_mode or "goals",
        kcal_goal=goal_row.kcal_goal,
        protein_goal=goal_row.protein_goal,
        fiber_goal=goal_row.fiber_goal,
        streak_days=goal_row.streak_days,
    )


async def _hard_block(user_id: str, entries: list[HardEntry] | None) -> str:
    """Render the user's hard profile for the prompt.

    Args:
        user_id: Supabase Auth UUID.
        entries: The live entries when the caller already loaded them this
            turn; read from the database when None.

    Raises:
        Exception: Any failure to read or render it (including
            ``ProfileTooLarge`` and unreadable clinical tables). The coach
            must not answer without the binding profile.
    """
    if entries is None:
        entries = await hard_profile.load_hard_profile(user_id)
    return hard_profile.render_block(entries, load_tables())


async def load_restrictions(
    user_id: str, entries: list[HardEntry] | None = None
) -> ContextBundle:
    """Load only what binds the coach's suggestions.

    Used when :func:`build_context` fails, so that a Redis or embeddings
    outage cannot strip the hard profile from the prompt. Postgres only: the
    ``user_goal`` row and the hard profile. Today's totals are left at their
    zero default and are not rendered by :func:`build_restrictions_prompt`.

    Args:
        user_id: Supabase Auth UUID.
        entries: The live hard entries if already loaded this turn.

    Returns:
        A ContextBundle with ``goals`` and the rendered hard profile.

    Raises:
        Exception: When the hard profile cannot be loaded or rendered.
    """
    session_factory = get_session()
    async with session_factory() as session:
        goals = _goal_summary(await session.get(UserGoal, user_id))
    return ContextBundle(
        today_totals=TodayTotals(),
        goals=goals,
        hard_block=await _hard_block(user_id, entries),
    )


async def build_context(
    user_id: str,
    entries: list[HardEntry] | None = None,
) -> ContextBundle:
    """Assemble the context bundle for build_system_prompt().

    Reads Redis today totals, Postgres goals + most recent weekly summary,
    and the user's soft profile (every live fact plus staple foods; no
    embedding call). A failed soft read leaves the profile out and logs.

    Args:
        user_id: Supabase Auth UUID.
        entries: The live hard entries if the caller already loaded them
            this turn; read from the database when None.

    Returns:
        A populated ContextBundle.
    """
    today_totals, hard_block = await asyncio.gather(
        get_today_totals(user_id), _hard_block(user_id, entries)
    )

    session_factory = get_session()
    async with session_factory() as session:
        goals = _goal_summary(await session.get(UserGoal, user_id))

        weekly_stmt = (
            select(WeeklySummary)
            .where(WeeklySummary.user_id == user_id)
            .order_by(WeeklySummary.week_start.desc())
            .limit(1)
        )
        weekly_row = (await session.execute(weekly_stmt)).scalars().first()
        weekly_pattern = (
            WeeklyPattern(
                avg_protein_g=weekly_row.avg_protein_g,
                days_hit_protein=weekly_row.days_hit_protein,
                weak_spots=weekly_row.weak_spots,
                missed_meals=weekly_row.missed_meals,
            )
            if weekly_row
            else None
        )

    # Mindful-mode users have no goals to reference; surface UL safety
    # breaches to the coaching agent instead.
    if goals is not None and goals.tracking_mode == "mindful":
        intake = await get_daily_intake(user_id, nutrition_today())
        goals.active_alerts = evaluate_safety(intake)

    profile, staples = await asyncio.gather(
        _load_soft_profile(user_id), fetch_staples(user_id)
    )

    return ContextBundle(
        today_totals=today_totals,
        goals=goals,
        weekly_pattern=weekly_pattern,
        hard_block=hard_block,
        profile=profile,
        staples=staples,
    )


_ROLE_AND_TONE = _TUNABLES.prompts.coaching_role_and_tone.strip()

_HARD_CONSTRAINTS = _TUNABLES.prompts.coaching_hard_constraints.strip()


def build_system_prompt(ctx: ContextBundle) -> str:
    """Assemble the ~456-token coaching system prompt from a ContextBundle.

    Follows the PRD §5.2 token budget: role/tone (~120), today totals
    (~80), weekly pattern (~120), soft profile (omitted if empty),
    accountability rules (~95), hard constraints (~112). The soft profile is
    every live fact, capped at ``memory.profile_max_chars`` (~350 tokens)
    plus one staples line.

    Note: this is consumed by the coaching agent (agent/coaching/agent.py), not
    the meal-logging graph — extraction/classification prompts in
    agent/meal_logging/meals.py are self-contained and don't need live user state.

    Args:
        ctx: Context bundle from build_context().

    Returns:
        The assembled system prompt string.
    """
    blocks = [_ROLE_AND_TONE]

    totals = ctx.today_totals
    today_block = (
        f"Today so far: {totals.kcal:.0f} kcal, {totals.protein_g:.0f}g protein, "
        f"{totals.fiber_g:.0f}g fiber, across {totals.n_meals} meal(s)."
    )
    goals_line = _goals_line(ctx.goals)
    if goals_line:
        today_block += f" {goals_line} Current streak: {ctx.goals.streak_days} day(s)."
    blocks.append(today_block)

    # Mindful mode: no goals, but surface any safety breaches.
    if ctx.goals and ctx.goals.tracking_mode == "mindful":
        blocks.append(
            "This user is in Mindful Eating mode — no calorie/macro targets. "
            "Do not frame advice around hitting goals."
        )
        if ctx.goals.active_alerts:
            alert_lines = "; ".join(
                f"{a.nutrient} {a.amount:.0f}{a.unit} (limit {a.limit:.0f}{a.unit}, "
                f"{a.source})"
                for a in ctx.goals.active_alerts
            )
            blocks.append(f"Safety alerts (intake at/above UL today): {alert_lines}.")

    if ctx.weekly_pattern:
        wp = ctx.weekly_pattern
        weekly_block = (
            f"This week's pattern: averaged {wp.avg_protein_g:.0f}g protein/day, "
            f"hit protein goal {wp.days_hit_protein}/7 days."
        )
        if wp.weak_spots:
            weekly_block += f" Weak spots: {', '.join(wp.weak_spots)}."
        if wp.missed_meals:
            weekly_block += f" Frequently missed: {', '.join(wp.missed_meals)}."
        blocks.append(weekly_block)

    blocks.extend(_restriction_blocks(ctx))

    accountability_rules = [
        "Accountability rules:",
        "- Reference today's actual progress toward goals when relevant.",
    ]
    if (
        ctx.goals
        and ctx.goals.protein_goal is not None
        and totals.protein_g < 0.6 * ctx.goals.protein_goal
    ):
        accountability_rules.append(
            "- Protein is below 60% of today's goal — gently flag this if "
            "the conversation allows."
        )
    blocks.append("\n".join(accountability_rules))

    blocks.append(_HARD_CONSTRAINTS)

    return "\n\n".join(blocks)


def _goals_line(goals: GoalSummary | None) -> str | None:
    """The daily targets sentence, or None in mindful mode or with no targets."""
    if (
        goals
        and goals.tracking_mode == "goals"
        and goals.kcal_goal is not None
        and goals.protein_goal is not None
        and goals.fiber_goal is not None
    ):
        return (
            f"Goals: {goals.kcal_goal:.0f} kcal, {goals.protein_goal:.0f}g protein, "
            f"{goals.fiber_goal:.0f}g fiber."
        )
    return None


def _restriction_blocks(ctx: ContextBundle) -> list[str]:
    """The hard profile, then soft preferences, for the coaching prompt."""
    blocks: list[str] = [ctx.hard_block] if ctx.hard_block else []
    profile_block = render_profile_block(ctx.profile, ctx.staples)
    if profile_block:
        blocks.append(profile_block)
    return blocks


def build_restrictions_prompt(ctx: ContextBundle) -> str:
    """Build the fallback coaching prompt from the goals row and hard profile.

    Used when the full context could not be built: role, daily targets,
    restrictions and hard constraints. Leaves out today's totals and the
    weekly pattern, because a bundle from :func:`load_restrictions` does not
    carry them. The targets are kept because without them the coach, asked
    about "my protein goal", tends to call the memory tools to record one.

    Args:
        ctx: Context bundle from load_restrictions().

    Returns:
        The assembled system prompt string.
    """
    goals_line = _goals_line(ctx.goals)
    blocks = [_ROLE_AND_TONE, *([goals_line] if goals_line else [])]
    blocks += [*_restriction_blocks(ctx), _HARD_CONSTRAINTS]
    return "\n\n".join(blocks)


__all__ = [
    "ContextBundle",
    "GoalSummary",
    "WeeklyPattern",
    "build_context",
    "build_restrictions_prompt",
    "build_system_prompt",
    "fetch_staples",
    "load_restrictions",
]
