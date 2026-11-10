"""Re-type legacy ``user_memory`` rows for the curated profile.

Rows written before migration 018 all have kind ``preference``. This asks
the extraction model to give each one a real kind (restriction, dislike,
like, habit, context) in profile wording, or to drop it when it is a
one-off, a duplicate or not about food.

Usage:
    PYTHONPATH=src uv run python -m backend.scripts.backfill_memory_profile \\
        [--user-id UUID] [--apply --backup FILE]

Without ``--apply`` it is a dry run: it prints what it would do and writes
nothing. With ``--apply`` it first appends each user's rows to the
``--backup`` JSONL file, since the curator's removals are hard deletes.
Changes go through agent/memory.py apply_ops as the curator, so
the usual rules hold (duplicates merge, the cap applies). Idempotent: a
second run finds no ``preference`` rows left for the users it processed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
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
- drop: it describes a single meal or day, a temporary state, a calorie
  or macro target, something not about food, or it repeats another fact in
  the list (keep one, drop the rest).

An allergy or intolerance is always a restriction, never something to drop.
When facts repeat, keep the strictest one: an allergy over an intolerance,
an intolerance over "avoids", and keep the word "allergic" or "allergy" in
the rewrite ("Allergic to milk", not "Avoids dairy").

A rewrite must keep the meaning: keep every food it names and any
comparison ("Prefers tuna salad over green goddess dressing", not "Prefers
tuna salad dressings"). If you cannot shorten it without changing the
meaning, return the original wording.

Return one decision for every handle. Do not invent facts.
"""

# Safety net under the model's decisions: a fact naming an allergy or
# intolerance is never dropped or softened. A duplicate allergy left behind
# is harmless and visible; a lost one is silent.
_SAFETY_TERMS = re.compile(
    r"\b(allerg\w*|intoleran\w*|anaphyla\w*|celiac|coeliac)\b", re.IGNORECASE
)

# A rewrite may only shorten a fact, never drop what it is about: every
# word of four or more letters in the original must survive, apart from
# these fillers. Otherwise the original wording is kept (a dry run turned
# "prefers tuna salad over ... dressings" into "Prefers tuna salad
# dressings"). Comparison words are not fillers, since they carry meaning.
_WORD = re.compile(r"[a-z]{4,}")
_FILLER_WORDS = frozenset(
    {"also", "always", "generally", "really", "usually", "very", "with"}
)


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
        Replace ops for kept facts and remove ops for dropped ones. A fact
        naming an allergy or intolerance always becomes a restriction. A
        rewrite is used only when it keeps the original's meaning words
        (and, for a restriction, still names the allergy); otherwise the
        original wording is kept.
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
        rewrite = (decision.fact or "").strip()[:MAX_FACT_CHARS]
        if _SAFETY_TERMS.search(fact.fact):
            keep_rewrite = (
                decision.action == "keep"
                and _SAFETY_TERMS.search(rewrite) is not None
                and _keeps_meaning(fact.fact, rewrite)
            )
            ops.append(
                ReplaceFact(
                    id=fact.id,
                    fact=rewrite if keep_rewrite else fact.fact,
                    kind="restriction",
                )
            )
        elif decision.action == "drop":
            ops.append(RemoveFact(id=fact.id))
        elif decision.kind is not None:
            text = rewrite if _keeps_meaning(fact.fact, rewrite) else fact.fact
            ops.append(ReplaceFact(id=fact.id, fact=text, kind=decision.kind))
    return ops


def _keeps_meaning(original: str, rewrite: str) -> bool:
    """Whether ``rewrite`` keeps every meaning word of ``original``."""
    if not rewrite:
        return False
    kept = set(_WORD.findall(rewrite.lower()))
    return all(
        word in kept or word in _FILLER_WORDS
        for word in _WORD.findall(original.lower())
    )


async def _users_with_legacy_rows() -> list[str]:
    session_factory = get_session()
    async with session_factory() as session:
        stmt = (
            select(UserMemory.user_id)
            .where(UserMemory.category == LEGACY_KIND, UserMemory.deleted_at.is_(None))
            .distinct()
        )
        return [str(user_id) for user_id in (await session.execute(stmt)).scalars()]


class BackupRow(BaseModel):
    """One ``user_memory`` row as it was before the backfill touched it."""

    id: str
    user_id: str
    fact: str
    embedding: list[float] | None
    category: str
    confidence: float
    source: str
    deleted_at: datetime | None
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


async def _backup_rows(user_id: str, path: Path) -> int:
    """Append every ``user_memory`` row of one user to a JSONL backup.

    The curator's removals are hard deletes, so this file is the only way
    to restore a fact the backfill dropped by mistake. A deliberate
    one-off snapshot, not a second source of truth.

    Args:
        user_id: Supabase Auth UUID.
        path: Backup file, appended to.

    Returns:
        The number of rows written.
    """
    session_factory = get_session()
    async with session_factory() as session:
        stmt = select(UserMemory).where(UserMemory.user_id == user_id)
        rows = list((await session.execute(stmt)).scalars().all())
    lines = [
        BackupRow(
            id=str(r.id),
            user_id=str(r.user_id),
            fact=r.fact,
            embedding=None if r.embedding is None else [float(x) for x in r.embedding],
            category=r.category,
            confidence=r.confidence,
            source=r.source,
            deleted_at=r.deleted_at,
            updated_at=r.updated_at,
        ).model_dump_json()
        for r in rows
    ]

    def _append() -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.writelines(line + "\n" for line in lines)

    await asyncio.to_thread(_append)
    return len(lines)


async def _backfill_user(
    user_id: str, *, apply: bool, backup: Path | None = None
) -> None:
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
        if backup is None:
            raise ValueError("--apply needs a backup file")
        n_saved = await _backup_rows(user_id, backup)
        print(f"  backed up {n_saved} rows to {backup}")
        outcome = await apply_ops(user_id, ops, "curator")
        for result in outcome.results:
            if not result.applied:
                print(f"  not applied ({result.reason}): {result.op.id}")


async def _run(user_id: str | None, *, apply: bool, backup: Path | None) -> None:
    try:
        users = [user_id] if user_id else await _users_with_legacy_rows()
        print(f"{'APPLY' if apply else 'DRY RUN'}: {len(users)} user(s)")
        # Sequential on purpose: a one-off job, and it keeps the LLM call
        # rate low.
        for uid in users:
            await _backfill_user(uid, apply=apply, backup=backup)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description="Re-type legacy user_memory rows.")
    parser.add_argument("--user-id", help="Only this user (default: all).")
    parser.add_argument("--apply", action="store_true", help="Write the changes.")
    parser.add_argument(
        "--backup",
        type=Path,
        help="JSONL file each user's rows are saved to before changes "
        "(required with --apply; it holds user data, keep it out of git).",
    )
    args = parser.parse_args(argv)
    if args.apply and args.backup is None:
        parser.error("--apply requires --backup FILE")
    asyncio.run(_run(args.user_id, apply=args.apply, backup=args.backup))
    return 0


if __name__ == "__main__":
    sys.exit(main())
