"""Re-type legacy ``user_memory`` rows for the curated profile.

Rows written before migration 018 all have kind ``preference``. This asks
the extraction model to give each one a real kind (restriction, dislike,
like, habit, context) in profile wording, or to drop it when it is a
one-off, a duplicate or not about food.

Usage:
    PYTHONPATH=src uv run python -m backend.scripts.backfill_memory_profile \\
        [--user-id UUID] [--apply]

Without ``--apply`` it is a dry run: it prints what it would do and writes
nothing. Changes go through agent/memory.py apply_ops as the curator, so
the usual rules hold (duplicates merge, the cap applies). Idempotent: a
second run finds no ``preference`` rows left for the users it processed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.agent.llm import FLASH_LITE_MODEL, make_llm
from backend.agent.memory import (
    LEGACY_KIND,
    MAX_FACT_CHARS,
    FactKind,
    MemoryFact,
    MemoryOp,
    RemoveFact,
    ReplaceFact,
    apply_ops,
    label_facts,
    load_profile,
)
from backend.db.models import UserMemory
from backend.db.session import dispose_engine, get_session

_SYSTEM = """\
You are tidying a list of facts a nutrition app stored about one user.
For every fact, decide:

- keep: it is a lasting fact about the user's eating. Give its kind and
  rewrite it short, in third person, without a name or full stop
  ("Dislikes mushrooms", "Usually skips breakfast").
    restriction: allergy, intolerance, religious or ethical rule, a food
      they must never be served.
    dislike: a food or preparation they do not want.
    like: a food, cuisine or flavour they enjoy.
    habit: a recurring pattern in when or how they eat.
    context: stable circumstances (cooks for a family, no oven, budget).
- drop: it describes a single meal or day, a temporary state, a medical
  diagnosis, a calorie or macro target, something not about food, or it
  repeats another fact in the list (keep one, drop the rest).

Return one decision for every handle. Do not invent facts.
"""


class Decision(BaseModel):
    """What to do with one legacy fact."""

    ref: str = Field(description="Handle of the fact, e.g. m3")
    action: Literal["keep", "drop"]
    kind: FactKind | None = None
    fact: str | None = None

    model_config = ConfigDict(extra="forbid")


class Decisions(BaseModel):
    """One decision per legacy fact."""

    decisions: list[Decision] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def plan_backfill(
    decisions: list[Decision], legacy: list[MemoryFact]
) -> list[MemoryOp]:
    """Convert model decisions into ops; undecided facts are left alone.

    Args:
        decisions: Model output.
        legacy: The user's ``preference`` rows, in the order they were
            shown to the model (handles m1..mN).

    Returns:
        Replace ops for kept facts and remove ops for dropped ones.
    """
    by_handle = {handle: fact for handle, fact in label_facts(legacy)}
    ops: list[MemoryOp] = []
    seen: set[str] = set()
    for decision in decisions:
        handle = decision.ref.strip().lower()
        fact = by_handle.get(handle)
        if fact is None or handle in seen:
            continue
        seen.add(handle)
        if decision.action == "drop":
            ops.append(RemoveFact(id=fact.id))
        elif decision.kind is not None:
            text = (decision.fact or fact.fact).strip()[:MAX_FACT_CHARS]
            ops.append(
                ReplaceFact(id=fact.id, fact=text or fact.fact, kind=decision.kind)
            )
    return ops


async def _users_with_legacy_rows() -> list[str]:
    session_factory = get_session()
    async with session_factory() as session:
        stmt = (
            select(UserMemory.user_id)
            .where(UserMemory.category == LEGACY_KIND, UserMemory.deleted_at.is_(None))
            .distinct()
        )
        return [str(user_id) for user_id in (await session.execute(stmt)).scalars()]


async def _backfill_user(user_id: str, *, apply: bool) -> None:
    legacy = [f for f in await load_profile(user_id) if f.kind == LEGACY_KIND]
    if not legacy:
        return
    listing = "\n".join(f"{handle} {fact.fact}" for handle, fact in label_facts(legacy))
    llm = make_llm(FLASH_LITE_MODEL).with_structured_output(Decisions)
    output: Decisions = await llm.ainvoke(
        [SystemMessage(content=_SYSTEM), HumanMessage(content=listing)]
    )
    ops = plan_backfill(output.decisions, legacy)
    by_id = {fact.id: fact.fact for fact in legacy}
    print(f"user {user_id}: {len(legacy)} legacy facts, {len(ops)} changes")
    for op in ops:
        before = by_id[op.id]
        if isinstance(op, RemoveFact):
            print(f"  drop     {before!r}")
        else:
            print(f"  {op.kind:<11}{before!r} -> {op.fact!r}")
    if apply and ops:
        outcome = await apply_ops(user_id, ops, "curator")
        for result in outcome.results:
            if not result.applied:
                print(f"  not applied ({result.reason}): {result.op.id}")


async def _run(user_id: str | None, *, apply: bool) -> None:
    try:
        users = [user_id] if user_id else await _users_with_legacy_rows()
        print(f"{'APPLY' if apply else 'DRY RUN'}: {len(users)} user(s)")
        # Sequential on purpose: a one-off job, and it keeps the LLM call
        # rate low.
        for uid in users:
            await _backfill_user(uid, apply=apply)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description="Re-type legacy user_memory rows.")
    parser.add_argument("--user-id", help="Only this user (default: all).")
    parser.add_argument("--apply", action="store_true", help="Write the changes.")
    args = parser.parse_args(argv)
    asyncio.run(_run(args.user_id, apply=args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
