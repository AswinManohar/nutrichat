"""Draft the hard-fact inference dataset from hand-written seeds (spec 013 T004).

Reads ``eval/cases/hard_fact_seeds.jsonl``, asks Gemini for paraphrases of each
seed that keep its meaning and label, and writes a draft for hand review
(T005). The draft is never the reviewed file: the script refuses to write to
``eval/cases/hard_fact_inference.jsonl``.

    PYTHONPATH=src python eval/gen_hard_fact_cases.py --dry-run
    PYTHONPATH=src python eval/gen_hard_fact_cases.py [--per-seed 5]
        [--seeds PATH] [--out PATH]

Costs one model call per seed (``--dry-run`` prints the plan and the call
count and calls nothing). Needs GOOGLE_API_KEY for a real run.

Dataset conventions
-------------------
Seed record: ``{seed_id, message, expected, stratum, type[, ask_ok]}``.

* ``expected`` lists the hard facts the message states about the patient, as
  ``{"type", "value"}`` with the value shaped like the entry models in
  ``backend.safety.profile``. It is non-empty only for three strata: clear
  first-person statements, corrections that state the corrected fact, and
  facts buried in a meal log.
* Every other stratum expects ``[]``: hedged, third person, past state,
  hypothetical, question and negation. A hedged statement ("I think I might
  be lactose intolerant") is not a fact to accept, so it expects ``[]`` and is
  marked ``"ask_ok": true``: asking the patient to confirm is a good outcome,
  silently accepting is a false positive. ``ask_ok`` is carried to every
  paraphrase of that seed. The eval does not read it yet.
* ``type`` is the hard type the seed exercises (allergy, diagnosis,
  medication, physical_limitation, nutrient_limit), also for rows with an
  empty ``expected``.

Draft record: the seed fields plus ``split`` ("tune" 80% / "holdout" 20%, a
hash of ``seed_id``, so a seed and all its paraphrases share one split) and
``source`` ("seed" or "generated"). The eval's loader forbids unknown keys, so
T005 must drop ``type``, ``source``, ``seed_id`` and ``ask_ok`` when it writes
the reviewed file (or the loader must be widened).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings

from backend.agent.llm import FLASH_LITE_MODEL
from backend.config import get_tunables

CASES = Path(__file__).parent / "cases"
DEFAULT_SEEDS = CASES / "hard_fact_seeds.jsonl"
DEFAULT_OUT = CASES / "hard_fact_inference.draft.jsonl"
REVIEWED = CASES / "hard_fact_inference.jsonl"
HOLDOUT_PERCENT = 20
MAX_CONCURRENCY = 8

_SYSTEM = """\
You write test messages for a nutrition app's fact-extraction eval.
Given one message a user might send to a nutrition coach, write paraphrases
that keep exactly the same meaning and the same speaker: who the fact is
about, its tense and certainty (stated, hedged, past, hypothetical, question,
negated, corrected), and every number and unit. Do not turn a hedge into a
statement or a third person into first person. Vary length, register, casing,
punctuation, typos, non-native English and food context (Indian, European,
East Asian and so on). Each paraphrase must be a different message. Return
only the paraphrases."""


class Seed(BaseModel):
    """One hand-written labelled message."""

    seed_id: str
    message: str
    expected: list[dict[str, Any]]
    stratum: str
    type: str
    ask_ok: bool = False

    model_config = ConfigDict(extra="forbid")


class Paraphrases(BaseModel):
    """Structured model output."""

    messages: list[str] = Field(description="Paraphrases of the message")


@dataclass(frozen=True)
class Plan:
    """What a run would do, before any model call."""

    seeds: int
    per_seed: int
    model_calls: int
    rows: int
    by_type: dict[str, int]
    by_stratum: dict[str, int]
    by_split: dict[str, int]


class OverwriteRefused(Exception):
    """The output path is the reviewed dataset."""


def split_of(seed_id: str) -> str:
    """Deterministic 80/20 split of a seed id: ``tune`` or ``holdout``."""
    digest = hashlib.sha256(seed_id.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    return "holdout" if bucket < HOLDOUT_PERCENT else "tune"


def check_out_path(out: Path, reviewed: Path = REVIEWED) -> None:
    """Refuse to write over the reviewed dataset.

    Raises:
        OverwriteRefused: when ``out`` resolves to ``reviewed``.
    """
    if out.resolve() == reviewed.resolve():
        raise OverwriteRefused(
            f"{out} is the reviewed dataset; write a draft and review it by hand"
        )


def load_seeds(path: Path) -> list[Seed]:
    """Read and validate the seed file; seed ids must be unique."""
    seeds = [
        Seed.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    ids = Counter(s.seed_id for s in seeds)
    duplicates = sorted(i for i, n in ids.items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate seed ids: {duplicates[:5]}")
    return seeds


def build_row(seed: Seed, message: str, source: str) -> dict[str, Any]:
    """One output row: the seed's label with this message and its split."""
    row: dict[str, Any] = {
        "seed_id": seed.seed_id,
        "message": message,
        "expected": seed.expected,
        "stratum": seed.stratum,
        "type": seed.type,
        "split": split_of(seed.seed_id),
        "source": source,
    }
    if seed.ask_ok:
        row["ask_ok"] = True
    return row


def build_rows(seed: Seed, paraphrases: list[str]) -> list[dict[str, Any]]:
    """The seed row followed by its distinct paraphrases.

    Blank paraphrases, ones equal to the seed (ignoring case and surrounding
    space) and repeats are dropped.
    """
    rows = [build_row(seed, seed.message, "seed")]
    seen = {seed.message.strip().lower()}
    for text in paraphrases:
        key = text.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(build_row(seed, text.strip(), "generated"))
    return rows


def make_plan(seeds: list[Seed], per_seed: int) -> Plan:
    """Counts of the rows a full run would write (seeds plus paraphrases)."""
    weight = 1 + per_seed
    by_type: Counter[str] = Counter()
    by_stratum: Counter[str] = Counter()
    by_split: Counter[str] = Counter()
    for seed in seeds:
        by_type[seed.type] += weight
        by_stratum[seed.stratum] += weight
        by_split[split_of(seed.seed_id)] += weight
    return Plan(
        seeds=len(seeds),
        per_seed=per_seed,
        model_calls=len(seeds),
        rows=len(seeds) * weight,
        by_type=dict(sorted(by_type.items())),
        by_stratum=dict(sorted(by_stratum.items())),
        by_split=dict(sorted(by_split.items())),
    )


def format_plan(plan: Plan) -> str:
    """Human-readable plan: counts per type, stratum and split."""
    lines = [
        f"seeds: {plan.seeds}  paraphrases per seed: {plan.per_seed}",
        f"estimated model calls: {plan.model_calls} ({FLASH_LITE_MODEL})",
        f"rows to write (seeds included, before de-duplication): {plan.rows}",
    ]
    for title, counts in (
        ("type", plan.by_type),
        ("stratum", plan.by_stratum),
        ("split", plan.by_split),
    ):
        lines.append(f"by {title}:")
        lines.extend(f"  {name}: {count}" for name, count in counts.items())
    return "\n".join(lines)


async def _paraphrase(
    agent: Agent[None, Paraphrases],
    seed: Seed,
    per_seed: int,
    gate: asyncio.Semaphore,
) -> list[str]:
    async with gate:
        result = await agent.run(
            f"Write {per_seed} paraphrases of this message:\n{seed.message}"
        )
    return result.output.messages[:per_seed]


async def generate(
    seeds: list[Seed], per_seed: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """Paraphrase every seed; returns the rows and the ids of failed seeds."""
    agent = Agent(
        GoogleModel(FLASH_LITE_MODEL),
        output_type=Paraphrases,
        system_prompt=_SYSTEM,
        model_settings=GoogleModelSettings(
            google_thinking_config={
                "thinking_budget": (
                    get_tunables().token_limits.extraction_thinking_budget
                )
            }
        ),
    )
    gate = asyncio.Semaphore(MAX_CONCURRENCY)
    results = await asyncio.gather(
        *(_paraphrase(agent, s, per_seed, gate) for s in seeds),
        return_exceptions=True,
    )
    rows: list[dict[str, Any]] = []
    failed: list[str] = []
    for seed, result in zip(seeds, results, strict=True):
        if isinstance(result, BaseException):
            print(f"FAILED {seed.seed_id}: {result!r}", file=sys.stderr)
            failed.append(seed.seed_id)
            rows.extend(build_rows(seed, []))
        else:
            rows.extend(build_rows(seed, result))
    return rows, failed


def write_rows(rows: list[dict[str, Any]], out: Path) -> None:
    """Write one JSON object per line."""
    out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def summarise(rows: list[dict[str, Any]]) -> str:
    """Counts of written rows per type, stratum and split."""
    lines = [f"rows written: {len(rows)}"]
    for key in ("type", "stratum", "split", "source"):
        lines.append(f"by {key}:")
        counts = Counter(r[key] for r in rows)
        lines.extend(f"  {name}: {n}" for name, n in sorted(counts.items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seeds", type=Path, default=DEFAULT_SEEDS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--per-seed", type=int, default=5)
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan, call no model"
    )
    args = parser.parse_args(argv)
    if args.per_seed < 1:
        parser.error("--per-seed must be at least 1")
    try:
        check_out_path(args.out)
    except OverwriteRefused as exc:
        parser.error(str(exc))
    seeds = load_seeds(args.seeds)
    print(format_plan(make_plan(seeds, args.per_seed)))
    if args.dry_run:
        return 0
    rows, failed = asyncio.run(generate(seeds, args.per_seed))
    write_rows(rows, args.out)
    print(summarise(rows))
    print(f"wrote {args.out}")
    if failed:
        print(f"{len(failed)} seeds got no paraphrases: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
