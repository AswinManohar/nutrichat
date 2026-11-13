from __future__ import annotations

import asyncio
import logging
import os

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.agent.llm import EMBEDDING_DIM, EMBEDDING_MODEL
from backend.agent.memory import (
    MemoryFact,
    load_profile,
    profile_active,
    render_profile_block,
)
from backend.agent.tools.history import get_staple_foods
from backend.agent.tools.mindful import (
    SafetyAlert,
    evaluate_safety,
    get_daily_intake,
)
from backend.config import get_tunables
from backend.core.nutrition_day import nutrition_today
from backend.db.models import UserGoal, UserMemory, WeeklySummary
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

_TOP_K_PREFERENCES = _TUNABLES.memory.top_k_preferences


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
    (goals + weekly pattern), and the user's preferences. For users on the
    curated profile (``profile_active``) that is the whole profile plus
    staple foods from their logs; otherwise the legacy pgvector top-3
    ``preferences``.
    """

    today_totals: TodayTotals
    goals: GoalSummary | None = None
    weekly_pattern: WeeklyPattern | None = None
    hard_block: str = ""
    preferences: list[str] = []
    profile_active: bool = False
    profile: list[MemoryFact] = []
    staples: dict[str, list[str]] = {}

    model_config = ConfigDict(extra="forbid")


async def _embed_query(text: str) -> list[float]:
    embeddings = GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        output_dimensionality=EMBEDDING_DIM,
    )
    return await embeddings.aembed_query(text)


async def _fetch_preferences(user_id: str, user_message: str) -> list[str]:
    """Top-3 most relevant preference facts via pgvector ANN.

    Only called when a user message is available to embed (per PRD §5.2 —
    the preferences block is conditional on `user_message` being given).
    """
    query_embedding = await _embed_query(user_message)

    session_factory = get_session()
    async with session_factory() as session:
        stmt = (
            select(UserMemory)
            .where(UserMemory.user_id == user_id, UserMemory.deleted_at.is_(None))
            .order_by(UserMemory.embedding.cosine_distance(query_embedding))
            .limit(_TOP_K_PREFERENCES)
        )
        result = await session.execute(stmt)
        return [row.fact for row in result.scalars().all()]


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
    user_message: str | None = None,
    entries: list[HardEntry] | None = None,
) -> ContextBundle:
    """Assemble the context bundle for build_system_prompt().

    Reads Redis today totals, Postgres goals + most recent weekly summary,
    and the user's preferences: the whole curated profile plus staple foods
    for users on the profile path (no embedding call), otherwise (when
    `user_message` is given) the top-3 pgvector-relevant preference facts.

    Args:
        user_id: Supabase Auth UUID.
        user_message: Latest user message, used to retrieve relevant
            preferences via pgvector ANN. Omitted for flows (e.g. meal
            logging) that don't need the preferences block.
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

    use_profile = profile_active(user_id)
    preferences: list[str] = []
    profile: list[MemoryFact] = []
    staples: dict[str, list[str]] = {}
    if use_profile:
        profile, staples = await asyncio.gather(
            load_profile(user_id), fetch_staples(user_id)
        )
    elif user_message:
        preferences = await _fetch_preferences(user_id, user_message)

    return ContextBundle(
        today_totals=today_totals,
        goals=goals,
        weekly_pattern=weekly_pattern,
        hard_block=hard_block,
        preferences=preferences,
        profile_active=use_profile,
        profile=profile,
        staples=staples,
    )


_ROLE_AND_TONE = _TUNABLES.prompts.coaching_role_and_tone.strip()

_HARD_CONSTRAINTS = _TUNABLES.prompts.coaching_hard_constraints.strip()


def build_system_prompt(ctx: ContextBundle) -> str:
    """Assemble the ~456-token coaching system prompt from a ContextBundle.

    Follows the PRD §5.2 token budget: role/tone (~120), today totals
    (~80), weekly pattern (~120), preferences (~150, omitted if empty),
    accountability rules (~95), hard constraints (~112). For users on the
    curated profile the preferences block is the whole profile instead,
    capped at ``memory.profile_max_chars`` (~350 tokens) plus one staples
    line.

    Note: this is consumed by the coaching agent (agent/coaching.py), not
    the meal-logging graph — extraction/classification prompts in
    agent/tools/meals.py are self-contained and don't need live user state.

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
    """The hard profile, then soft preferences, for the coaching prompt.

    The hard block is rendered for every user; soft facts only for users on
    the curated profile, the legacy top-3 preferences otherwise.
    """
    blocks: list[str] = [ctx.hard_block] if ctx.hard_block else []
    if ctx.profile_active:
        profile_block = render_profile_block(ctx.profile, ctx.staples)
        if profile_block:
            blocks.append(profile_block)
    elif ctx.preferences:
        blocks.append("Known preferences: " + "; ".join(ctx.preferences) + ".")
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
