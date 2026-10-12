"""Background curators: keep a user's preference profile current.

Both run in Celery (see workers/tasks.py), never on the reply path, so
they add nothing to chat latency.

* :func:`curate_turn` runs after each turn. One structured-output call
  sees the whole profile and returns add / replace / remove / set_diet
  operations.
* :func:`infer_log_habits` runs weekly per active logger and rewrites the
  few facts inferred from their meal logs.

agent/memory.py apply_ops enforces what each is allowed to do.
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.llm import FLASH_LITE_MODEL, make_llm
from backend.agent.memory import (
    DIET_CHIPS,
    MAX_FACT_CHARS,
    AddFact,
    ApplyOutcome,
    FactKind,
    MemoryOp,
    ProfileState,
    RemoveFact,
    ReplaceFact,
    SetDietChip,
    apply_ops,
    label_facts,
    load_state,
    normalize_fact,
)
from backend.agent.tools.history import get_category_breakdown, get_staple_foods
from backend.config import get_tunables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()
_CURATOR_SYSTEM = _TUNABLES.prompts.profile_curator_system
_LOG_HABITS_SYSTEM = _TUNABLES.prompts.log_habits_system
_LOG_SOURCE = "inferred_from_logs"


class CuratorOp(BaseModel):
    """One operation proposed by the curator model.

    Flat on purpose: Gemini structured output handles one object with
    optional fields more reliably than a discriminated union. Converted to
    a typed MemoryOp by :func:`to_memory_ops`.
    """

    action: Literal["add", "replace", "remove", "set_diet"]
    ref: str | None = Field(
        default=None, description="Handle of an existing fact, e.g. m3"
    )
    fact: str | None = Field(default=None, description="Fact text for add/replace")
    kind: FactKind | None = Field(default=None, description="Kind for add/replace")
    chip: str | None = Field(default=None, description="Diet setting for set_diet")

    model_config = ConfigDict(extra="forbid")


class CuratorOutput(BaseModel):
    """Operations for one conversation turn; empty for most turns."""

    ops: list[CuratorOp] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


_curator_llm = make_llm(FLASH_LITE_MODEL).with_structured_output(CuratorOutput)


def build_curator_input(state: ProfileState, user_input: str, agent_reply: str) -> str:
    """Render the profile and the turn as the curator's user message.

    Args:
        state: Current profile state from ``memory.load_state``.
        user_input: The user's message this turn.
        agent_reply: The agent's reply this turn.

    Returns:
        Prompt text listing facts by handle, diet settings, removed facts,
        how full the profile is, and the turn.
    """
    cfg = _TUNABLES.memory
    used_chars = sum(len(f.fact) for f in state.facts)
    fill = max(
        len(state.facts) / cfg.profile_max_facts, used_chars / cfg.profile_max_chars
    )
    facts = "\n".join(
        f"{handle} [{fact.kind}] {fact.fact}"
        for handle, fact in label_facts(state.facts)
    )
    removed = "\n".join(f"- {t}" for t in state.tombstones)
    off = sorted(DIET_CHIPS - set(state.diet_chips))
    return "\n\n".join(
        [
            f"Current profile ({fill:.0%} full):\n{facts or '(empty)'}",
            f"Diet settings on: {', '.join(state.diet_chips) or '(none)'}",
            f"Diet settings available: {', '.join(off)}",
            f"Removed by the user:\n{removed or '(none)'}",
            f"Conversation turn:\nUser: {user_input}\nAssistant: {agent_reply}",
        ]
    )


def to_memory_ops(proposed: list[CuratorOp], state: ProfileState) -> list[MemoryOp]:
    """Convert model output to typed ops, dropping malformed ones.

    Handles ("m3") are mapped back to fact ids. An op that is missing a
    required field or names an unknown handle is skipped: the model's
    output is a suggestion, and apply_ops is the authority.
    """
    by_handle = {handle: fact.id for handle, fact in label_facts(state.facts)}
    ops: list[MemoryOp] = []
    for item in proposed:
        fact = (item.fact or "").strip()[:MAX_FACT_CHARS]
        fact_id = by_handle.get((item.ref or "").strip().lower())
        if item.action == "add" and fact and item.kind:
            ops.append(AddFact(fact=fact, kind=item.kind))
        elif item.action == "replace" and fact_id and fact and item.kind:
            ops.append(ReplaceFact(id=fact_id, fact=fact, kind=item.kind))
        elif item.action == "remove" and fact_id:
            ops.append(RemoveFact(id=fact_id))
        elif item.action == "set_diet" and item.chip:
            ops.append(SetDietChip(chip=item.chip.strip().lower(), on=True))
        else:
            logger.info("curator proposed an unusable op: %s", item.model_dump())
    return ops


async def curate_turn(user_id: str, user_input: str, agent_reply: str) -> ApplyOutcome:
    """Update a user's profile from one conversation turn.

    Reads the profile, asks the curator model for operations, and applies
    them as the "curator" actor. No database session is held open during
    the model call.

    Args:
        user_id: Supabase Auth UUID.
        user_input: The user's message.
        agent_reply: The agent's response.

    Returns:
        What was applied; empty when the turn changed nothing.
    """
    if not user_input.strip():
        return ApplyOutcome()
    state = await load_state(user_id)
    output: CuratorOutput = await _curator_llm.ainvoke(
        [
            SystemMessage(content=_CURATOR_SYSTEM),
            HumanMessage(content=build_curator_input(state, user_input, agent_reply)),
        ]
    )
    ops = to_memory_ops(output.ops, state)
    if not ops:
        return ApplyOutcome()
    return await apply_ops(user_id, ops, "curator")


class LogHabit(BaseModel):
    """One pattern inferred from a month of meal logs."""

    fact: str
    kind: Literal["habit", "like"]

    model_config = ConfigDict(extra="forbid")


class LogHabitsOutput(BaseModel):
    """Patterns inferred from the logs; empty when none is clear."""

    facts: list[LogHabit] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


_log_habits_llm = make_llm(FLASH_LITE_MODEL).with_structured_output(LogHabitsOutput)


def build_log_habits_input(
    state: ProfileState,
    staples: dict[str, list[str]],
    by_meal_type: list[dict],
    *,
    days: int,
    max_facts: int,
) -> str:
    """Render the log statistics and profile as the weekly job's message.

    Args:
        state: Current profile state from ``memory.load_state``.
        staples: Output of ``get_staple_foods``.
        by_meal_type: Output of ``get_category_breakdown``.
        days: Length of the window the statistics cover.
        max_facts: Most facts the model may return.

    Returns:
        Prompt text for the log-habits model.
    """
    staple_lines = "\n".join(
        f"- {meal_type}: {', '.join(foods)}" for meal_type, foods in staples.items()
    )
    stat_lines = "\n".join(
        f"- {row['meal_type']}: {row['n_meals']} meals on {row['days_logged']} of "
        f"{days} days, avg {row['avg_kcal']:.0f} kcal, "
        f"{row['avg_protein_g']:.0f}g protein"
        for row in by_meal_type
    )
    profile = "\n".join(f"- [{f.kind}] {f.fact}" for f in state.facts)
    removed = "\n".join(f"- {t}" for t in state.tombstones)
    return "\n\n".join(
        [
            f"Foods logged repeatedly in the last {days} days:\n"
            f"{staple_lines or '(none)'}",
            f"Per meal type:\n{stat_lines or '(none)'}",
            f"Diet settings on: {', '.join(state.diet_chips) or '(none)'}",
            f"Already in the profile:\n{profile or '(empty)'}",
            f"Removed by the user:\n{removed or '(none)'}",
            f"Return at most {max_facts} facts.",
        ]
    )


def plan_log_habit_ops(
    proposed: list[LogHabit], state: ProfileState, max_facts: int
) -> list[MemoryOp]:
    """Turn this week's inferred habits into ops that replace last week's.

    Facts the job wrote before and did not propose again are removed; ones
    proposed again are left untouched; new ones are added.
    """
    wanted: dict[str, LogHabit] = {}
    for habit in proposed:
        text = habit.fact.strip()[:MAX_FACT_CHARS]
        key = normalize_fact(text)
        if key and key not in wanted and len(wanted) < max_facts:
            wanted[key] = LogHabit(fact=text, kind=habit.kind)

    ops: list[MemoryOp] = []
    for fact in state.facts:
        if fact.source != _LOG_SOURCE:
            continue
        if normalize_fact(fact.fact) in wanted:
            del wanted[normalize_fact(fact.fact)]
        else:
            ops.append(RemoveFact(id=fact.id))
    ops.extend(AddFact(fact=h.fact, kind=h.kind) for h in wanted.values())
    return ops


async def infer_log_habits(user_id: str) -> ApplyOutcome:
    """Rewrite one user's log-inferred habit facts from the last month.

    Reads the staples and per-meal-type statistics (both derived from
    ``meal_log``), asks the model for a few interpreted patterns, and
    applies them as the "weekly" actor: it may only add soft facts and
    replace its own. No database session is open during the model call.

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        What was applied; empty when there is nothing to infer from.
    """
    cfg = _TUNABLES.memory
    days = cfg.staples_window_days
    staples = await get_staple_foods(user_id, days=days)
    if not staples:
        return ApplyOutcome()
    by_meal_type = await get_category_breakdown(user_id, days)
    state = await load_state(user_id)
    output: LogHabitsOutput = await _log_habits_llm.ainvoke(
        [
            SystemMessage(content=_LOG_HABITS_SYSTEM),
            HumanMessage(
                content=build_log_habits_input(
                    state,
                    staples,
                    by_meal_type,
                    days=days,
                    max_facts=cfg.weekly_habits_max_facts,
                )
            ),
        ]
    )
    ops = plan_log_habit_ops(output.facts, state, cfg.weekly_habits_max_facts)
    if not ops:
        return ApplyOutcome()
    return await apply_ops(user_id, ops, "weekly")


__all__ = [
    "CuratorOp",
    "CuratorOutput",
    "LogHabit",
    "LogHabitsOutput",
    "build_curator_input",
    "build_log_habits_input",
    "curate_turn",
    "infer_log_habits",
    "plan_log_habit_ops",
    "to_memory_ops",
]
