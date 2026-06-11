from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError

from backend.agent.llm import COACHING_MODEL, FLASH_LITE_MODEL, make_llm
from backend.agent.tools.history import (
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

    time_range: Literal["today", "yesterday", "this_week", "last_7_days", "custom"]
    date_from: date | None = None
    date_to: date | None = None
    nutrients: list[str] = Field(default_factory=list)
    include_goals: bool = False

    model_config = ConfigDict(extra="forbid")


_QUERY_PARSE_SYSTEM = _TUNABLES.prompts.query_parse_system

_RESPONSE_SYSTEM = _TUNABLES.prompts.coaching_response_system

_query_parser_llm = make_llm(FLASH_LITE_MODEL).with_structured_output(QueryParsed)


async def parse_query(message: str) -> QueryParsed:
    """Extract time range, nutrients, and goal intent from a nutrition question.

    Args:
        message: Raw user message, e.g. "how much protein today?".

    Returns:
        Parsed query with time_range, optional date bounds, nutrients, and
        include_goals.
    """
    return await _query_parser_llm.ainvoke(
        [
            SystemMessage(content=_QUERY_PARSE_SYSTEM),
            HumanMessage(content=message),
        ]
    )


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
    return parsed.date_from or today, parsed.date_to or today


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
        "goals" depending on the query.
    """
    macro_nutrients = [n for n in parsed.nutrients if n in _MACRO_ALIASES]
    micro_nutrients = [n for n in parsed.nutrients if n not in _MACRO_ALIASES]

    data: dict = {}

    if macro_nutrients or not parsed.nutrients:
        if parsed.time_range == "today" and not micro_nutrients:
            try:
                totals = await get_today_totals(user_id)
                data["today_totals"] = totals.model_dump()
            except (RedisError, OSError):
                # Redis unavailable — fall back to Postgres (coaching spec §6).
                date_from, date_to = _resolve_date_range(parsed)
                data["macros"] = await get_macros_for_range(user_id, date_from, date_to)
        else:
            date_from, date_to = _resolve_date_range(parsed)
            data["macros"] = await get_macros_for_range(user_id, date_from, date_to)

    if micro_nutrients:
        date_from, date_to = _resolve_date_range(parsed)
        data["micronutrients"] = await get_micronutrients_for_range(
            user_id, date_from, date_to, micro_nutrients
        )

    if parsed.include_goals:
        session_factory = get_session()
        async with session_factory() as session:
            goal = await session.get(UserGoal, user_id)
            if goal is not None:
                data["goals"] = {
                    "kcal_goal": goal.kcal_goal,
                    "protein_goal": goal.protein_goal,
                    "fiber_goal": goal.fiber_goal,
                }

    return data


async def generate_response(message: str, data: dict) -> str:
    """Generate a grounded natural-language answer from fetched data.

    Args:
        message: The user's original question.
        data: Output of fetch_data().

    Returns:
        Natural language response, under 3 sentences.
    """
    llm = make_llm(COACHING_MODEL)
    response = await llm.ainvoke(
        [
            SystemMessage(content=_RESPONSE_SYSTEM),
            HumanMessage(
                content=(
                    f"User question: {message}\n\n"
                    f"Data:\n{json.dumps(data, default=str)}"
                )
            ),
        ]
    )
    return response.content


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

        macro_data = data.get("today_totals") or data.get("macros")
        if (
            macro_data is not None
            and macro_data["n_meals"] == 0
            and not micro_nutrients
        ):
            return "No meals logged for that period yet."

        if micro_nutrients and not data.get("micronutrients"):
            return f"I don't have data on {', '.join(micro_nutrients)} for that period."

        return await generate_response(message, data)


__all__ = [
    "CoachingAgent",
    "QueryParsed",
    "fetch_data",
    "generate_response",
    "parse_query",
]
