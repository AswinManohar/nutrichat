"""The coach's in-turn memory tools: remember, forget, set_diet.

Offered to the response agent for every signed-in user, and
only called on an explicit request, so an ordinary coaching turn makes no
extra model round trip. Soft facts go through agent/memory/facts.py apply_ops as
the "user" actor. Hard facts (restrictions, diet settings) become pending
hard-profile entries that bind only after the user confirms; removing one
only requests its retirement. The tool's reply tells the model to ask.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Literal, Protocol

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from backend.agent.memory.facts import (
    MAX_FACT_CHARS,
    PENDING_ADD,
    PENDING_REMOVAL,
    AddFact,
    AddRestriction,
    FactKind,
    MemoryOp,
    RemoveFact,
    SetDietChip,
    apply_ops,
    load_profile,
    normalize_fact,
)
from backend.safety import profile
from backend.safety.tables import load_tables

logger = logging.getLogger(__name__)

RememberKind = Literal["restriction", FactKind]

_CONFIRM_NOTE = (
    "It does not apply until the user confirms. The app asks them to confirm "
    "at the end of your reply: do not ask yourself."
)

# A coaching turn sets a list here before the reply is generated; a tool that
# adds a pending hard entry appends to it, so the turn can read it back from
# the template (agent/coaching/agent.py) instead of leaving it for the next turn.
hard_writes: ContextVar[list[bool] | None] = ContextVar("hard_writes", default=None)


def _note_hard_write() -> None:
    writes = hard_writes.get()
    if writes is not None:
        writes.append(True)


class _HasUserId(Protocol):
    user_id: str | None


async def _apply_one(user_id: str, op: MemoryOp) -> tuple[bool, str]:
    outcome = await apply_ops(user_id, [op], "user")
    result = outcome.results[0]
    return result.applied, result.reason


async def remember_fact(user_id: str, fact: str, kind: RememberKind) -> str:
    """Store one fact the user asked to have remembered.

    Args:
        user_id: Supabase Auth UUID.
        fact: Short third-person statement, e.g. "Dislikes mushrooms".
        kind: restriction, dislike, like, cuisine, budget, cooking_time, habit or
            context.

    Returns:
        A sentence for the model saying what happened.
    """
    text = fact.strip()[:MAX_FACT_CHARS]
    if not text:
        return "Nothing saved: the fact was empty."
    if kind == "restriction":
        applied, reason = await _apply_one(user_id, AddRestriction(fact=text))
        if applied:
            _note_hard_write()
            return f'Recorded as pending: "{text}". {_CONFIRM_NOTE}'
        return f"Nothing saved: {reason}."
    applied, reason = await _apply_one(user_id, AddFact(fact=text, kind=kind))
    if applied:
        return f'Saved to the profile: "{text}".'
    return f"Nothing saved: {reason}."


async def _forget_candidates(user_id: str) -> list[tuple[str, str, str]]:
    """Every removable fact as (text, kind, id); kind is soft, pending or confirmed."""
    soft = [(f.fact, "soft", f.id) for f in await load_profile(user_id)]
    tables = load_tables()
    hard = [
        (profile.label_for(e, tables), e.state, e.id)
        for e in await profile.load_hard_profile(user_id)
    ]
    return soft + hard


async def forget_fact(user_id: str, fact: str) -> str:
    """Remove the stored fact that matches ``fact``.

    Matching is by normalized text: an exact match wins, otherwise the
    query must be contained in (or contain) exactly one stored fact. A soft
    fact is removed. A hard fact (allergy, restriction, diet setting, ...) is
    only marked for removal: it keeps binding until the user confirms.

    Args:
        user_id: Supabase Auth UUID.
        fact: The fact to remove, as worded in the profile or close to it.

    Returns:
        A sentence for the model saying what happened.
    """
    query = normalize_fact(fact)
    try:
        candidates = await _forget_candidates(user_id)
    except Exception as exc:  # noqa: BLE001 - the model must be told, not crash the turn
        logger.error("forget: loading the profile failed for %s: %s", user_id, exc)
        return "Nothing removed: the profile could not be read."
    if not query or not candidates:
        return "Nothing removed: the profile has no matching fact."
    matches = [c for c in candidates if normalize_fact(c[0]) == query]
    if not matches:
        matches = [
            c
            for c in candidates
            if query in normalize_fact(c[0]) or normalize_fact(c[0]) in query
        ]
    if not matches:
        stored = "; ".join(c[0] for c in candidates)
        return f"Nothing removed: no stored fact matches. Stored facts: {stored}."
    if len(matches) > 1:
        options = "; ".join(c[0] for c in matches)
        return f"Nothing removed: several facts match ({options}). Ask which one."
    text, kind, fact_id = matches[0]
    if kind == "soft":
        applied, reason = await _apply_one(user_id, RemoveFact(id=fact_id))
        if applied:
            return f'Removed from the profile: "{text}".'
        return f"Nothing removed: {reason}."
    try:
        if kind == "pending":
            await profile.deny(user_id, fact_id)
            return f'Dropped the unconfirmed entry: "{text}".'
        await profile.request_retirement(user_id, fact_id)
    except profile.ProfileError as exc:
        return f"Nothing removed: {exc}."
    _note_hard_write()
    return (
        f'Removal of "{text}" is {PENDING_REMOVAL}: it stays in effect until '
        "then. The app asks the user to confirm at the end of your reply: do "
        "not ask yourself."
    )


async def set_diet_setting(user_id: str, setting: str, on: bool) -> str:
    """Ask for one of the app's diet settings to be switched on or off.

    Neither direction applies at once: switching on adds a pending entry and
    switching off requests retirement of the confirmed one.

    Args:
        user_id: Supabase Auth UUID.
        setting: Diet setting key, e.g. "vegetarian" or "gluten_free".
        on: True to switch it on, False to switch it off.

    Returns:
        A sentence for the model saying what happened.
    """
    chip = setting.strip().lower().replace(" ", "_").replace("-", "_")
    applied, reason = await _apply_one(user_id, SetDietChip(chip=chip, on=on))
    if not applied:
        return f"Nothing changed: {reason}."
    if reason == "no change":
        return f"The {chip} diet setting was already {'on' if on else 'off'}."
    if on:
        _note_hard_write()
        return f"The {chip} diet setting is {PENDING_ADD}. {_CONFIRM_NOTE}"
    _note_hard_write()
    return (
        f"Switching the {chip} diet setting off is {PENDING_REMOVAL}: it stays on "
        "until then. The app asks the user to confirm at the end of your reply."
    )


memory_toolset: FunctionToolset[_HasUserId] = FunctionToolset()


@memory_toolset.tool
async def remember(ctx: RunContext[_HasUserId], fact: str, kind: RememberKind) -> str:
    """Save a lasting fact about the user's eating to their profile.

    Args:
        fact: Short third-person statement without a full stop, e.g.
            "Dislikes mushrooms" or "Allergic to peanuts".
        kind: restriction (an allergy or food that must never be served; it
            is pending until the user confirms), dislike, like, cuisine, budget,
            cooking_time, habit or context.
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
    """Ask to switch one of the app's diet settings on or off.

    The change waits for the user's confirmation; say so and ask them.

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
    "hard_writes",
    "memory_toolset",
    "remember_fact",
    "set_diet_setting",
]
