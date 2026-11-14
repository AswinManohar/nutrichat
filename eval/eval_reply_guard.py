"""Eval for the reply guard (spec 013 R10, T059).

Cases: ``eval/cases/reply_guard.jsonl``. Each is a prose reply, the patient's
hard entries, whether the reply violates them (``violation``) and which layer
should decide (``layer``: lexical, usda, glide, or none when no layer fires).
A case marked ``live_only`` needs the GLiDE judgment (layer 3).

Two modes:

* ``--offline`` runs layers 1-2 only (lexical and USDA-description matching; no
  model, no network, the bundled USDA file only) on the cases that do not need
  GLiDE. Exit code 1 on any missed violation (a reply that should be blocked
  but is shown) or false alarm.
* ``--live`` adds the GLiDE judgment (needs ``FASTINO_API_KEY``) and scores all
  cases. Exit code 1 on any missed violation.

Reports precision and recall of violations, the layer that decided each case,
and the share of cases that reach layer 3.

    PYTHONPATH=src python eval/eval_reply_guard.py --offline
    PYTHONPATH=src python eval/eval_reply_guard.py --live
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.agent import reply_judge
from backend.agent.food import usda_local
from backend.safety import profile, reply_guard
from backend.safety.matching import term_rules
from backend.safety.reply_guard import GuardVerdict
from backend.safety.tables import ClinicalTables, load_tables

CASES = Path(__file__).parent / "cases" / "reply_guard.jsonl"
_EPOCH = datetime(2026, 11, 1, tzinfo=UTC)

Layer = Literal["lexical", "usda", "glide", "none"]


class CaseEntry(BaseModel):
    """One hard entry of the patient in a case."""

    type: profile.EntryType
    value: dict[str, Any]
    state: Literal["pending", "confirmed"] = "confirmed"

    model_config = ConfigDict(extra="forbid")


class Case(BaseModel):
    """A reply, a profile and the expected verdict."""

    id: str
    entries: list[CaseEntry]
    reply: str
    violation: bool
    layer: Layer
    live_only: bool = False

    model_config = ConfigDict(extra="forbid")


class Outcome(BaseModel):
    """What the guard did with one case."""

    id: str
    expected: bool
    got: bool
    layer: Layer
    reached_layer3: bool

    model_config = ConfigDict(extra="forbid")


class Score(BaseModel):
    """Totals over a set of outcomes."""

    cases: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    by_layer: dict[str, int] = Field(default_factory=dict)
    layer3_share: float

    model_config = ConfigDict(extra="forbid")


def load_cases(path: Path = CASES) -> list[Case]:
    """Read and validate the cases; every entry value must be valid.

    Raises:
        ValueError: On an invalid case or a duplicate id.
    """
    cases = [
        Case.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("duplicate case ids")
    for case in cases:
        for entry in case.entries:
            profile.parse_value(entry.type, entry.value)
    return cases


def to_entries(case: Case) -> list[profile.HardEntry]:
    """The case's entries as hard entries (confirmed ones carry a timestamp)."""
    return [
        profile.HardEntry(
            id=f"{case.id}-{i}",
            type=e.type,
            value=profile.parse_value(e.type, e.value),
            source="patient",
            state=e.state,
            created_at=_EPOCH,
            created_by="patient",
            confirmed_at=_EPOCH if e.state == "confirmed" else None,
        )
        for i, e in enumerate(case.entries)
    ]


def outcome_of(case: Case, verdict: GuardVerdict, tables: ClinicalTables) -> Outcome:
    """Turn a verdict into an outcome.

    ``reached_layer3`` is true when layers 1-2 found a food phrase and no
    violation for a patient with a food constraint (the case GLiDE would be
    asked about), whether or not GLiDE ran.
    """
    entries = to_entries(case)
    reached = (
        not verdict.violations
        and bool(verdict.food_phrases)
        and bool(term_rules(entries, tables))
    ) or verdict.layer == "glide"
    layer: Layer = verdict.layer if verdict.violations else "none"
    return Outcome(
        id=case.id,
        expected=case.violation,
        got=bool(verdict.violations),
        layer=layer,
        reached_layer3=reached,
    )


def score(outcomes: list[Outcome]) -> Score:
    """Precision and recall of violations, layers used and layer-3 share."""
    tp = sum(o.expected and o.got for o in outcomes)
    fp = sum(o.got and not o.expected for o in outcomes)
    fn = sum(o.expected and not o.got for o in outcomes)
    return Score(
        cases=len(outcomes),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=tp / (tp + fp) if tp + fp else 1.0,
        recall=tp / (tp + fn) if tp + fn else 1.0,
        by_layer=dict(Counter(o.layer for o in outcomes)),
        layer3_share=(
            sum(o.reached_layer3 for o in outcomes) / len(outcomes) if outcomes else 0.0
        ),
    )


async def run_case(case: Case, tables: ClinicalTables, live: bool) -> Outcome:
    """Run the guard on one case (layers 1-2, plus GLiDE when ``live``)."""
    entries = to_entries(case)
    if live:
        verdict = await reply_judge.guard(case.reply, entries, tables)
    else:
        verdict = await reply_guard.scan(case.reply, entries, tables, usda_local.lookup)
    return outcome_of(case, verdict, tables)


async def run(cases: list[Case], live: bool) -> int:
    """Print the report; return the exit code."""
    tables = load_tables()
    selected = [c for c in cases if live or not c.live_only]
    outcomes = [await run_case(c, tables, live) for c in selected]
    by_id = {c.id: c for c in selected}
    for o in outcomes:
        wrong = o.expected != o.got
        layer_note = (
            "" if o.layer == by_id[o.id].layer else f" (expected {by_id[o.id].layer})"
        )
        print(f"{'BAD' if wrong else 'ok '} {o.id}: layer={o.layer}{layer_note}")
    result = score(outcomes)
    print(
        f"\ncases {result.cases} (skipped {len(cases) - len(selected)} needing GLiDE), "
        f"precision {result.precision:.3f}, recall {result.recall:.3f}, "
        f"layers {result.by_layer}, reaching layer 3: {100 * result.layer3_share:.0f}%"
    )
    if live:
        return 1 if result.false_negatives else 0
    return 1 if result.false_negatives or result.false_positives else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="layers 1-2 only")
    mode.add_argument("--live", action="store_true", help="add the GLiDE layer")
    parser.add_argument("--cases", type=Path, default=CASES)
    args = parser.parse_args(argv)
    return asyncio.run(run(load_cases(args.cases), live=args.live))


if __name__ == "__main__":
    sys.exit(main())
