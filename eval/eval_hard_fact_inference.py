"""Hard-fact inference eval (spec 013 US4, tasks T077, T078).

Replays hand-labelled single messages through the live curator model and
GLiDE, then scores the typed hard facts and soft preferences they produce.
Needs GOOGLE_API_KEY and FASTINO_API_KEY. Writes nothing to any database: the
profile is empty for every case, so a candidate is always new.

Dataset: ``eval/cases/hard_fact_inference.jsonl``, one case per line::

    {"message": "...", "expected": [{"type": "allergy",
     "value": {"allergen_group": "shellfish"}}], "stratum": "...",
     "split": "tune" | "holdout"}

``expected`` lists the hard facts the message states about the patient (empty
for a message that states none). A soft preference is
``{"type": "soft", "value": {"kind": "dislike", "contains": "coriander"}}``.
The dataset is generated later with the owner's approval; without the file the
script says so and stops.

Reports, per run:

* precision and recall per hard type and per band (accept, ask) at the
  thresholds in ``tunables.yaml``;
* precision and recall of soft preferences (at ``memory.save_min_probability``);
* a reliability curve and the Brier score of GLiDE's probability against
  whether the candidate matched an expected fact;
* a threshold sweep over (ask, accept) chosen on ``tune``, then the chosen
  pair scored on ``holdout``.

    PYTHONPATH=src python eval/eval_hard_fact_inference.py [--dataset PATH]
        [--save-predictions OUT.json | --load-predictions IN.json]

``--load-predictions`` re-runs the report and sweep from saved scores with no
model call, so thresholds can be explored for free.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from backend.agent.memory import AddFact, ProfileState, ReplaceFact
from backend.agent.memory_curator import (
    _CURATOR_SYSTEM,
    CuratorOutput,
    _curator_llm,
    build_curator_input,
    to_hard_candidates,
    to_memory_ops,
)
from backend.agent.memory_judge import HardAdd, judge_hard, judge_ops
from backend.config import get_tunables
from backend.safety import profile
from backend.safety.tables import load_tables

DATASET = Path(__file__).parent / "cases" / "hard_fact_inference.jsonl"
SOFT = "soft"
BANDS = ("accept", "ask")
DEFAULT_ASK_GRID = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
DEFAULT_ACCEPT_GRID = (0.8, 0.85, 0.9, 0.95, 0.98)


class Expected(BaseModel):
    """One fact a message states: a hard entry type and value, or a soft one."""

    type: str
    value: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class Case(BaseModel):
    """One labelled message."""

    message: str
    expected: list[Expected]
    stratum: str
    split: str
    # Hedged statements ("I think I might be lactose intolerant"): asking is
    # right, saving silently is not. An ask-band candidate on such a case is
    # neither a hit nor an error; an accept-band one is a false positive.
    ask_ok: bool = False
    # Provenance written by eval/gen_hard_fact_cases.py; not scored.
    seed_id: str | None = None
    type: str | None = None
    source: str | None = None

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Prediction:
    """A candidate the pipeline produced; ``probability`` None = unscored."""

    type: str
    value: dict[str, Any]
    probability: float | None


@dataclass
class Counts:
    """True positives, false positives and false negatives."""

    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, other: Counts) -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn


@dataclass
class Scored:
    """Counts of one pass over cases at one (ask, accept) pair."""

    by_type: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    by_band: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    overall: Counts = field(default_factory=Counts)
    expected_total: int = 0


# --- pure metrics (unit-tested) ----------------------------------------------------


def band_of(probability: float | None, ask: float, accept: float) -> str:
    """The band of a candidate that adds a constraint: accept, ask or drop.

    An unscored candidate always asks, as in ``select_hard_ops``.
    """
    if probability is None:
        return "ask"
    if probability >= accept:
        return "accept"
    return "ask" if probability >= ask else "drop"


def normalise(entry_type: str, value: dict[str, Any]) -> str:
    """A canonical string for a value, so equal facts compare equal.

    Hard values go through their model (defaults, key order); soft values are
    compared by kind and lowercase text.
    """
    if entry_type == SOFT:
        return json.dumps(
            {k: str(v).lower() for k, v in sorted(value.items())}, sort_keys=True
        )
    return profile.parse_value(entry_type, value).model_dump_json(exclude_none=True)


def matches(prediction: Prediction, expected: Expected) -> bool:
    """Whether a prediction states the expected fact."""
    if prediction.type != expected.type:
        return False
    if prediction.type == SOFT:
        want = str(expected.value.get("contains", "")).lower()
        kind_ok = expected.value.get("kind") in (None, prediction.value.get("kind"))
        return kind_ok and want in str(prediction.value.get("fact", "")).lower()
    try:
        return normalise(prediction.type, prediction.value) == normalise(
            expected.type, expected.value
        )
    except ValueError:
        return False


def is_correct(prediction: Prediction, expected: list[Expected]) -> bool:
    """Whether the prediction states any expected fact (for calibration)."""
    return any(matches(prediction, e) for e in expected)


def score_case(
    predictions: list[Prediction],
    expected: list[Expected],
    ask: float,
    accept: float,
    soft_min: float,
    ask_ok: bool = False,
) -> Scored:
    """Count tp/fp/fn for one case at one pair of thresholds.

    Hard predictions are placed in a band; a dropped one is neither a tp nor an
    fp, and the expected fact it would have matched is a false negative. Soft
    predictions are kept at ``soft_min`` (the soft save threshold). Each
    expected fact is matched by at most one prediction. On an ``ask_ok`` case
    an unmatched hard candidate in the ask band is not counted.
    """
    scored = Scored(expected_total=len(expected))
    unmatched = list(expected)
    for prediction in predictions:
        if prediction.type == SOFT:
            kept = prediction.probability is None or prediction.probability >= soft_min
            band = "soft"
        else:
            band = band_of(prediction.probability, ask, accept)
            kept = band != "drop"
        if not kept:
            continue
        hit = next((e for e in unmatched if matches(prediction, e)), None)
        if hit is None and ask_ok and band == "ask":
            continue
        counts = Counts(tp=int(hit is not None), fp=int(hit is None))
        if hit is not None:
            unmatched.remove(hit)
        scored.by_type[prediction.type].add(counts)
        scored.by_band[band].add(counts)
        scored.overall.add(counts)
    for missed in unmatched:
        scored.by_type[missed.type].fn += 1
        scored.overall.fn += 1
    return scored


def merge(parts: list[Scored]) -> Scored:
    """Sum the counts of several cases."""
    total = Scored()
    for part in parts:
        total.expected_total += part.expected_total
        total.overall.add(part.overall)
        for key, counts in part.by_type.items():
            total.by_type[key].add(counts)
        for key, counts in part.by_band.items():
            total.by_band[key].add(counts)
    return total


def precision(counts: Counts) -> float | None:
    """tp / (tp + fp); None when nothing was predicted."""
    denom = counts.tp + counts.fp
    return counts.tp / denom if denom else None


def recall(counts: Counts) -> float | None:
    """tp / (tp + fn); None when nothing was expected."""
    denom = counts.tp + counts.fn
    return counts.tp / denom if denom else None


def band_recall(scored: Scored, band: str) -> float | None:
    """Share of all expected hard facts that landed in this band."""
    hard_expected = (
        scored.expected_total - scored.by_type[SOFT].tp - scored.by_type[SOFT].fn
    )
    return scored.by_band[band].tp / hard_expected if hard_expected else None


def brier(points: list[tuple[float, bool]]) -> float | None:
    """Mean squared error of probability against outcome; None without points."""
    if not points:
        return None
    return sum((p - float(ok)) ** 2 for p, ok in points) / len(points)


def reliability(points: list[tuple[float, bool]], bins: int = 10):
    """Reliability curve: per probability bin, count, mean p and accuracy."""
    rows = []
    for i in range(bins):
        low, high = i / bins, (i + 1) / bins
        inside = [
            (p, ok)
            for p, ok in points
            if low <= p < high or (i == bins - 1 and p == 1.0)
        ]
        if inside:
            rows.append(
                {
                    "low": low,
                    "high": high,
                    "n": len(inside),
                    "mean_p": sum(p for p, _ in inside) / len(inside),
                    "accuracy": sum(ok for _, ok in inside) / len(inside),
                }
            )
    return rows


def sweep(
    cases: list[tuple[Case, list[Prediction]]],
    asks: tuple[float, ...],
    accepts: tuple[float, ...],
    soft_min: float,
    min_accept_precision: float,
) -> list[dict[str, Any]]:
    """Score every (ask, accept) pair with ask <= accept, best first.

    Ranked by: accept-band precision at or above ``min_accept_precision``
    first, then recall of hard facts (accept + ask bands), then the share the
    accept band takes over (fewer questions to the patient).
    """
    rows = []
    for ask, accept in itertools.product(asks, accepts):
        if ask > accept:
            continue
        scored = merge(
            [
                score_case(p, c.expected, ask, accept, soft_min, c.ask_ok)
                for c, p in cases
            ]
        )
        hard = Counts()
        for key, counts in scored.by_type.items():
            if key != SOFT:
                hard.add(counts)
        accept_precision = precision(scored.by_band["accept"])
        rows.append(
            {
                "ask": ask,
                "accept": accept,
                "accept_precision": accept_precision,
                "ask_precision": precision(scored.by_band["ask"]),
                "hard_recall": recall(hard),
                "accept_recall": band_recall(scored, "accept"),
                "meets_target": accept_precision is None
                or accept_precision >= min_accept_precision,
            }
        )
    rows.sort(
        key=lambda r: (
            r["meets_target"],
            r["hard_recall"] or 0.0,
            r["accept_recall"] or 0.0,
        ),
        reverse=True,
    )
    return rows


# --- dataset and live pipeline ---


def load_cases(path: Path) -> list[Case]:
    """Read the dataset; every line must be a valid case."""
    cases = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip():
            try:
                cases.append(Case.model_validate_json(line))
            except ValueError as exc:
                raise SystemExit(f"{path}:{number}: {exc}") from exc
    return cases


async def predict(case: Case) -> list[Prediction]:
    """Run one message through the curator and GLiDE; no writes.

    The profile is empty, so every candidate is new and its probability is the
    whole decision. The assistant reply is not given (as on a coaching turn).
    """
    tables = load_tables()
    state = ProfileState()
    output: CuratorOutput = await _curator_llm.ainvoke(
        [
            SystemMessage(content=_CURATOR_SYSTEM),
            HumanMessage(
                content=build_curator_input(state, case.message, "", [], tables)
            ),
        ]
    )
    soft_ops = [
        op
        for op in to_memory_ops(output.ops, state)
        if isinstance(op, AddFact | ReplaceFact)
    ]
    hard = [
        c
        for c in to_hard_candidates(output, case.message, [], tables)
        if isinstance(c, HardAdd)
    ]
    soft_scores, hard_scores = await asyncio.gather(
        judge_ops(case.message, soft_ops, state),
        judge_hard(case.message, hard, [], tables),
    )
    predictions = [
        Prediction(SOFT, {"kind": op.kind, "fact": op.fact}, score)
        for op, score in zip(soft_ops, soft_scores, strict=True)
    ]
    predictions += [
        Prediction(c.type, c.value.model_dump(exclude_none=True), score)
        for c, score in zip(hard, hard_scores, strict=True)
    ]
    return predictions


async def predict_all(cases: list[Case], concurrency: int) -> list[list[Prediction]]:
    """Predict every case, ``concurrency`` at a time."""
    gate = asyncio.Semaphore(concurrency)

    async def one(case: Case) -> list[Prediction]:
        async with gate:
            return await predict(case)

    return list(await asyncio.gather(*(one(c) for c in cases)))


# --- report ---


def _pct(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.1%}"


def print_scored(title: str, scored: Scored) -> None:
    """Precision and recall per type and band."""
    print(f"\n{title}")
    print(f"{'':22}{'tp':>5}{'fp':>5}{'fn':>5}  {'precision':>9}  {'recall':>7}")
    for key in sorted(scored.by_type):
        c = scored.by_type[key]
        print(
            f"  type {key:16}{c.tp:5}{c.fp:5}{c.fn:5}  {_pct(precision(c)):>9}  "
            f"{_pct(recall(c)):>7}"
        )
    for key in (*BANDS, SOFT):
        if key in scored.by_band:
            c = scored.by_band[key]
            share = band_recall(scored, key) if key != SOFT else recall(c)
            print(
                f"  band {key:16}{c.tp:5}{c.fp:5}{c.fn:5}  {_pct(precision(c)):>9}  "
                f"{_pct(share):>7}"
            )


def report(
    cases: list[tuple[Case, list[Prediction]]],
    ask: float,
    accept: float,
    soft_min: float,
) -> None:
    """Print the per-type, per-band, calibration and soft sections."""
    scored = merge(
        [score_case(p, c.expected, ask, accept, soft_min, c.ask_ok) for c, p in cases]
    )
    print_scored(f"Thresholds ask={ask} accept={accept} ({len(cases)} cases)", scored)
    points = [
        (pred.probability, is_correct(pred, case.expected))
        for case, preds in cases
        for pred in preds
        if pred.type != SOFT and pred.probability is not None
    ]
    unscored = sum(
        1
        for _, preds in cases
        for p in preds
        if p.type != SOFT and p.probability is None
    )
    print(
        f"\nCalibration of hard candidates ({len(points)} scored, {unscored} unscored)"
    )
    print(f"  Brier score: {brier(points)!s}")
    for row in reliability(points):
        print(
            f"  p in [{row['low']:.1f}, {row['high']:.1f}): n={row['n']:3} "
            f"mean p={row['mean_p']:.2f} accuracy={row['accuracy']:.2f}"
        )


def print_sweep(rows: list[dict[str, Any]], title: str) -> None:
    """Print the sweep table."""
    print(f"\n{title}")
    print("  ask  accept  accept-prec  ask-prec  hard-recall  accept-recall  target")
    for r in rows:
        print(
            f"  {r['ask']:.2f}  {r['accept']:.2f}   {_pct(r['accept_precision']):>9}"
            f"  {_pct(r['ask_precision']):>8}  {_pct(r['hard_recall']):>11}"
            f"  {_pct(r['accept_recall']):>13}  {'ok' if r['meets_target'] else 'MISS'}"
        )


def run_report(
    cases: list[tuple[Case, list[Prediction]]], min_accept_precision: float
) -> None:
    """Report at the configured thresholds, then sweep on tune and check holdout."""
    cfg = get_tunables().memory
    ask, accept = cfg.hard_ask_min_probability, cfg.hard_accept_min_probability
    report(cases, ask, accept, cfg.save_min_probability)
    tune = [(c, p) for c, p in cases if c.split == "tune"]
    holdout = [(c, p) for c, p in cases if c.split == "holdout"]
    if not tune:
        print("\nNo cases with split=tune: skipping the sweep.")
        return
    rows = sweep(
        tune,
        DEFAULT_ASK_GRID,
        DEFAULT_ACCEPT_GRID,
        cfg.save_min_probability,
        min_accept_precision,
    )
    print_sweep(rows, f"Threshold sweep on tune ({len(tune)} cases), best first")
    best = rows[0]
    if not best["meets_target"]:
        print(f"\nNo pair reaches accept-band precision {min_accept_precision:.0%}.")
    if holdout:
        print(
            f"\nHoldout ({len(holdout)} cases) at the best tune pair "
            f"ask={best['ask']} accept={best['accept']}:"
        )
        report(holdout, best["ask"], best["accept"], cfg.save_min_probability)
    else:
        print("\nNo cases with split=holdout.")


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--min-accept-precision", type=float, default=0.98)
    saved = parser.add_mutually_exclusive_group()
    saved.add_argument("--save-predictions", type=Path)
    saved.add_argument("--load-predictions", type=Path)
    args = parser.parse_args(argv)
    if not args.dataset.exists():
        print(
            f"No dataset at {args.dataset}. The hard-fact inference dataset is "
            "generated separately, with the owner's approval (spec 013 T005); "
            "nothing to evaluate yet."
        )
        return 2
    cases = load_cases(args.dataset)
    if args.load_predictions:
        raw = json.loads(args.load_predictions.read_text())
        predictions = [[Prediction(**p) for p in preds] for preds in raw]
        if len(predictions) != len(cases):
            raise SystemExit("saved predictions do not match the dataset")
    else:
        predictions = asyncio.run(predict_all(cases, args.concurrency))
        if args.save_predictions:
            args.save_predictions.write_text(
                json.dumps([[asdict(p) for p in preds] for preds in predictions])
            )
    run_report(list(zip(cases, predictions, strict=True)), args.min_accept_precision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
