"""The coach's in-turn memory tools: remember, forget, set_diet.

Offered to the response agent only for users on the curated profile, and
only called on an explicit request, so an ordinary coaching turn makes no
extra model round trip. Every write goes through agent/memory.py apply_ops
as the "user" actor: these are things the user asked for directly.
"""

from __future__ import annotations

from typing import Protocol

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from backend.agent.memory import (
    MAX_FACT_CHARS,
    AddFact,
    FactKind,
    MemoryOp,
    RemoveFact,
    SetDietChip,
    apply_ops,
    load_profile,
    normalize_fact,
)


class _HasUserId(Protocol):
    user_id: str | None


async def _apply_one(user_id: str, op: MemoryOp) -> tuple[bool, str]:
    outcome = await apply_ops(user_id, [op], "user")
    result = outcome.results[0]
    return result.applied, result.reason


async def remember_fact(user_id: str, fact: str, kind: FactKind) -> str:
    """Store one fact the user asked to have remembered.

    Args:
        user_id: Supabase Auth UUID.
        fact: Short third-person statement, e.g. "Dislikes mushrooms".
        kind: restriction, dislike, like, habit or context.

    Returns:
        A sentence for the model saying what happened.
    """
    text = fact.strip()[:MAX_FACT_CHARS]
    if not text:
        return "Nothing saved: the fact was empty."
    applied, reason = await _apply_one(user_id, AddFact(fact=text, kind=kind))
    if applied:
        return f'Saved to the profile: "{text}".'
    return f"Nothing saved: {reason}."


async def forget_fact(user_id: str, fact: str) -> str:
    """Remove the stored fact that matches ``fact``.

    Matching is by normalized text: an exact match wins, otherwise the
    query must be contained in (or contain) exactly one stored fact.

    Args:
        user_id: Supabase Auth UUID.
        fact: The fact to remove, as worded in the profile or close to it.

    Returns:
        A sentence for the model saying what happened.
    """
    query = normalize_fact(fact)
    profile = await load_profile(user_id)
    if not query or not profile:
        return "Nothing removed: the profile has no matching fact."
    matches = [f for f in profile if normalize_fact(f.fact) == query]
    if not matches:
        matches = [
            f
            for f in profile
            if query in normalize_fact(f.fact) or normalize_fact(f.fact) in query
        ]
    if not matches:
        stored = "; ".join(f.fact for f in profile)
        return f"Nothing removed: no stored fact matches. Stored facts: {stored}."
    if len(matches) > 1:
        options = "; ".join(f.fact for f in matches)
        return f"Nothing removed: several facts match ({options}). Ask which one."
    applied, reason = await _apply_one(user_id, RemoveFact(id=matches[0].id))
    if applied:
        return f'Removed from the profile: "{matches[0].fact}".'
    return f"Nothing removed: {reason}."


async def set_diet_setting(user_id: str, setting: str, on: bool) -> str:
    """Switch one of the app's diet settings on or off.

    Args:
        user_id: Supabase Auth UUID.
        setting: Diet setting key, e.g. "vegetarian" or "gluten_free".
        on: True to switch it on, False to switch it off.

    Returns:
        A sentence for the model saying what happened.
    """
    chip = setting.strip().lower().replace(" ", "_").replace("-", "_")
    applied, reason = await _apply_one(user_id, SetDietChip(chip=chip, on=on))
    state = "on" if on else "off"
    if not applied:
        return f"Nothing changed: {reason}."
    if reason == "no change":
        return f"The {chip} diet setting was already {state}."
    return f"The {chip} diet setting is now {state}."


memory_toolset: FunctionToolset[_HasUserId] = FunctionToolset()


@memory_toolset.tool
async def remember(ctx: RunContext[_HasUserId], fact: str, kind: FactKind) -> str:
    """Save a lasting fact about the user's eating to their profile.

    Args:
        fact: Short third-person statement without a full stop, e.g.
            "Dislikes mushrooms" or "Allergic to peanuts".
        kind: restriction (must never be served), dislike, like, habit or
            context.
    """
    if ctx.deps.user_id is None:
        return "Nothing saved: memory is not available."
    return await remember_fact(ctx.deps.user_id, fact, kind)


@memory_toolset.tool
async def forget(ctx: RunContext[_HasUserId], fact: str) -> str:
    """Remove a fact from the user's profile.

    Args:
        fact: The fact to remove, worded as it appears in the profile.
    """
    if ctx.deps.user_id is None:
        return "Nothing removed: memory is not available."
    return await forget_fact(ctx.deps.user_id, fact)


@memory_toolset.tool
async def set_diet(ctx: RunContext[_HasUserId], setting: str, on: bool) -> str:
    """Switch one of the app's diet settings on or off.

    Args:
        setting: One of vegan, vegetarian, pescatarian, keto, paleo,
            gluten_free, dairy_free, no_nuts, low_carb, low_sodium,
            low_sugar, high_protein.
        on: True when the user adopts it, False when they drop it.
    """
    if ctx.deps.user_id is None:
        return "Nothing changed: memory is not available."
    return await set_diet_setting(ctx.deps.user_id, setting, on)


__all__ = [
    "forget_fact",
    "memory_toolset",
    "remember_fact",
    "set_diet_setting",
]
