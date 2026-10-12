"""Background curator: keeps a user's preference profile current.

Runs after the reply has been sent (Celery, see workers/tasks.py), so it
adds nothing to chat latency. One structured-output call per turn sees the
whole profile and returns add / replace / remove / set_diet operations;
agent/memory.py apply_ops enforces what the curator is allowed to do.
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
)
from backend.config import get_tunables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()
_CURATOR_SYSTEM = _TUNABLES.prompts.profile_curator_system


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


__all__ = [
    "CuratorOp",
    "CuratorOutput",
    "build_curator_input",
    "curate_turn",
    "to_memory_ops",
]
