from __future__ import annotations

import os

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.agent.llm import EMBEDDING_DIM, EMBEDDING_MODEL
from backend.agent.tools.mindful import (
    SafetyAlert,
    evaluate_safety,
    get_daily_intake,
)
from backend.config import get_tunables
from backend.core.nutrition_day import nutrition_today
from backend.db.models import UserGoal, UserMemory, WeeklySummary
from backend.db.redis_client import TodayTotals, get_today_totals
from backend.db.session import get_session

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
    dietary_prefs: dict
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
    (goals + weekly pattern), and pgvector (top-3 relevant preferences).
    """

    today_totals: TodayTotals
    goals: GoalSummary | None = None
    weekly_pattern: WeeklyPattern | None = None
    preferences: list[str] = []

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
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.embedding.cosine_distance(query_embedding))
            .limit(_TOP_K_PREFERENCES)
        )
        result = await session.execute(stmt)
        return [row.fact for row in result.scalars().all()]


async def build_context(user_id: str, user_message: str | None = None) -> ContextBundle:
    """Assemble the context bundle for build_system_prompt().

    Reads Redis today totals, Postgres goals + most recent weekly summary,
    and (when `user_message` is given) the top-3 pgvector-relevant
    preference facts.

    Args:
        user_id: Supabase Auth UUID.
        user_message: Latest user message, used to retrieve relevant
            preferences via pgvector ANN. Omitted for flows (e.g. meal
            logging) that don't need the preferences block.

    Returns:
        A populated ContextBundle.
    """
    today_totals = await get_today_totals(user_id)

    session_factory = get_session()
    async with session_factory() as session:
        goal_row = await session.get(UserGoal, user_id)
        goals = (
            GoalSummary(
                tracking_mode=goal_row.tracking_mode or "goals",
                kcal_goal=goal_row.kcal_goal,
                protein_goal=goal_row.protein_goal,
                fiber_goal=goal_row.fiber_goal,
                dietary_prefs=goal_row.dietary_prefs,
                streak_days=goal_row.streak_days,
            )
            if goal_row
            else None
        )

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

    preferences: list[str] = []
    if user_message:
        preferences = await _fetch_preferences(user_id, user_message)

    return ContextBundle(
        today_totals=today_totals,
        goals=goals,
        weekly_pattern=weekly_pattern,
        preferences=preferences,
    )


_ROLE_AND_TONE = _TUNABLES.prompts.coaching_role_and_tone.strip()

_HARD_CONSTRAINTS = _TUNABLES.prompts.coaching_hard_constraints.strip()


def build_system_prompt(ctx: ContextBundle) -> str:
    """Assemble the ~456-token coaching system prompt from a ContextBundle.

    Follows the PRD §5.2 token budget: role/tone (~120), today totals
    (~80), weekly pattern (~120), preferences (~150, omitted if empty),
    accountability rules (~95), hard constraints (~112).

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
    if (
        ctx.goals
        and ctx.goals.tracking_mode == "goals"
        and ctx.goals.kcal_goal is not None
        and ctx.goals.protein_goal is not None
        and ctx.goals.fiber_goal is not None
    ):
        today_block += (
            f" Goals: {ctx.goals.kcal_goal:.0f} kcal, "
            f"{ctx.goals.protein_goal:.0f}g protein, "
            f"{ctx.goals.fiber_goal:.0f}g fiber. "
            f"Current streak: {ctx.goals.streak_days} day(s)."
        )
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

    if ctx.preferences:
        blocks.append("Known preferences: " + "; ".join(ctx.preferences) + ".")

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


__all__ = [
    "ContextBundle",
    "GoalSummary",
    "WeeklyPattern",
    "build_context",
    "build_system_prompt",
]
