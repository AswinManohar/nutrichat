from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from redis.exceptions import RedisError

from backend.agent.cost import record_run_cost
from backend.agent.llm import COACHING_MODEL, FLASH_LITE_MODEL
from backend.agent.tools.history import (
    get_food_breakdown_for_range,
    get_macros_for_range,
    get_micronutrients_for_range,
)
from backend.config import get_tunables
from backend.db.models import UserGoal
from backend.db.redis_client import get_today_totals
from backend.db.session import get_session

# Macro column aliases map to meal_log columns — structural, not tunable.
_MACRO_ALIASES = {"kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"}

_TUNABLES = get_tunables()


class QueryParsed(BaseModel):
    """Structured nutrition question parsed by parse_query()."""

    time_range: Literal[
        "today",
        "yesterday",
        "this_week",
        "last_7_days",
        "this_month",
        "last_30_days",
        "last_90_days",
        "last_month",
        "custom",
    ]
    date_from: date | None = None
    date_to: date | None = None
    nutrients: list[str] = Field(default_factory=list)
    include_goals: bool = False
    include_foods: bool = False

    model_config = ConfigDict(extra="forbid")


_UNIT_SUFFIXES = ("_mcg", "_mg", "_g", "_iu")


def _humanize_nutrient_name(nutrient: str) -> str:
    """Convert a raw nutrient identifier into a human-readable name.

    Strips trailing unit suffixes (e.g. "_mcg", "_mg", "_g") and replaces
    underscores with spaces, e.g. "vitamin_d_mcg" -> "vitamin D",
    "water_g" -> "water".

    Args:
        nutrient: Raw nutrient field name, e.g. "vitamin_d_mcg".

    Returns:
        Human-readable nutrient name, e.g. "vitamin D".
    """
    name = nutrient
    for suffix in _UNIT_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    words = name.split("_")
    return " ".join("D" if w.lower() == "d" else w for w in words)


_QUERY_PARSE_SYSTEM = _TUNABLES.prompts.query_parse_system

_RESPONSE_SYSTEM = _TUNABLES.prompts.coaching_response_system

# Thinking off (extraction-tier): query parsing is a structured-output call
# that gates every coaching turn — skip the dynamic-thinking latency. The
# response agent below keeps thinking ON for answer quality.
_parse_agent = Agent(
    GoogleModel(FLASH_LITE_MODEL),
    output_type=QueryParsed,
    system_prompt=_QUERY_PARSE_SYSTEM,
    model_settings=GoogleModelSettings(
        google_thinking_config={
            "thinking_budget": _TUNABLES.token_limits.extraction_thinking_budget
        }
    ),
)

_response_agent = Agent(
    GoogleModel(COACHING_MODEL),
    system_prompt=_RESPONSE_SYSTEM,
)


async def parse_query(message: str) -> QueryParsed:
    """Extract time range, nutrients, and goal intent from a nutrition question.

    Args:
        message: Raw user message, e.g. "how much protein today?".

    Returns:
        Parsed query with time_range, optional date bounds, nutrients, and
        include_goals.
    """
    today = date.today()
    prompt = f"Today's date is {today.isoformat()}.\n\n{message}"
    result = await _parse_agent.run(prompt)
    record_run_cost(result, FLASH_LITE_MODEL, operation="parse_query")
    return result.output


def _resolve_date_range(parsed: QueryParsed) -> tuple[date, date]:
    """Map a parsed time_range to a concrete inclusive date range."""
    today = date.today()
    if parsed.time_range == "today":
        return today, today
    if parsed.time_range == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if parsed.time_range == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, today
    if parsed.time_range == "last_7_days":
        return today - timedelta(days=6), today
    if parsed.time_range == "this_month":
        return today.replace(day=1), today
    if parsed.time_range == "last_30_days":
        return today - timedelta(days=29), today
    if parsed.time_range == "last_90_days":
        return today - timedelta(days=89), today
    if parsed.time_range == "last_month":
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        return last_of_prev_month.replace(day=1), last_of_prev_month
    # custom: trust explicit bounds, but never silently collapse to today
    # when the parser failed to provide them.
    if parsed.date_from is not None and parsed.date_to is not None:
        return parsed.date_from, parsed.date_to
    return today - timedelta(days=29), today


def _build_period(date_from: date, date_to: date, label: str) -> dict:
    """Build the period metadata block attached to fetch_data() output.

    Args:
        date_from: Inclusive start date of the resolved range.
        date_to: Inclusive end date of the resolved range.
        label: The QueryParsed.time_range value (e.g. "last_30_days").

    Returns:
        Dict with date_from, date_to (ISO strings), days (inclusive count),
        and label.
    """
    days = (date_to - date_from).days + 1
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "days": days,
        "label": label,
    }


async def fetch_data(user_id: str, parsed: QueryParsed) -> dict:
    """Fetch grounding data for the response generator per the data fetcher table.

    Today + macro-only queries hit Redis (falling back to Postgres on
    Redis errors). Any other macro range, or any micronutrient query, hits
    Postgres directly. Goals are fetched alongside when requested.

    Args:
        user_id: Supabase Auth UUID.
        parsed: Output of parse_query().

    Returns:
        Dict with any of "today_totals", "macros", "micronutrients",
        "goals", "foods" depending on the query.
    """
    macro_nutrients = [n for n in parsed.nutrients if n in _MACRO_ALIASES]
    micro_nutrients = [n for n in parsed.nutrients if n not in _MACRO_ALIASES]

    data: dict = {}

    if macro_nutrients or not parsed.nutrients:
        if parsed.time_range == "today" and not micro_nutrients:
            try:
                totals = await get_today_totals(user_id)
                data["today_totals"] = totals.model_dump()
                today = date.today()
                data["period"] = _build_period(today, today, "today")
            except (RedisError, OSError):
                # Redis unavailable — fall back to Postgres (coaching spec §6).
                date_from, date_to = _resolve_date_range(parsed)
                data["macros"] = await get_macros_for_range(user_id, date_from, date_to)
                data["period"] = _build_period(date_from, date_to, parsed.time_range)
        else:
            date_from, date_to = _resolve_date_range(parsed)
            data["macros"] = await get_macros_for_range(user_id, date_from, date_to)
            data["period"] = _build_period(date_from, date_to, parsed.time_range)

    if micro_nutrients:
        date_from, date_to = _resolve_date_range(parsed)
        data["micronutrients"] = await get_micronutrients_for_range(
            user_id, date_from, date_to, micro_nutrients
        )
        if "period" not in data:
            data["period"] = _build_period(date_from, date_to, parsed.time_range)

    if parsed.include_goals:
        session_factory = get_session()
        async with session_factory() as session:
            goal = await session.get(UserGoal, user_id)
            if goal is not None:
                data["goals"] = {
                    "kcal_goal": goal.kcal_goal,
                    "protein_goal": goal.protein_goal,
                    "fiber_goal": goal.fiber_goal,
                    "dietary_prefs": goal.dietary_prefs,
                }

    if parsed.include_foods:
        date_from, date_to = _resolve_date_range(parsed)
        data["foods"] = await get_food_breakdown_for_range(user_id, date_from, date_to)

    return data


async def generate_response(message: str, data: dict) -> str:
    """Generate a grounded natural-language answer from fetched data.

    Args:
        message: The user's original question.
        data: Output of fetch_data().

    Returns:
        Natural language response, under 3 sentences.
    """
    content = f"User question: {message}\n\nData:\n{json.dumps(data, default=str)}"
    result = await _response_agent.run(content)
    record_run_cost(result, COACHING_MODEL, operation="coaching_response")
    return result.output


class CoachingAgent:
    """Linear pipeline: parse_query -> fetch_data -> generate_response."""

    async def handle(self, user_id: str, message: str) -> str:
        """Answer a nutrition question grounded in the user's logged data.

        Args:
            user_id: Supabase Auth UUID.
            message: User's nutrition question.

        Returns:
            Grounded natural-language response, or a graceful "no data"
            message when nothing has been logged for the requested range.
        """
        parsed = await parse_query(message)
        data = await fetch_data(user_id, parsed)

        micro_nutrients = [n for n in parsed.nutrients if n not in _MACRO_ALIASES]

        if micro_nutrients and not data.get("micronutrients"):
            names = ", ".join(_humanize_nutrient_name(n) for n in micro_nutrients)
            return f"I don't have data on {names} for that period."

        return await generate_response(message, data)


__all__ = [
    "CoachingAgent",
    "QueryParsed",
    "fetch_data",
    "generate_response",
    "parse_query",
]
