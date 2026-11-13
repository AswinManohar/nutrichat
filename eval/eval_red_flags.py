"""Offline gate for the red-flag screen (spec 013 SC-007, FR-018).

Runs ``eval/cases/red_flags.jsonl`` through ``backend.safety.red_flags.screen``.
No model is called. Passes when every ``expect_match`` case hits its rule, at
most 1% of the ordinary cases are screened, and p99 screen time is under 50 ms.

    PYTHONPATH=src python eval/eval_red_flags.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.safety.red_flags import RedFlagMatch, screen

CASES = Path(__file__).parent / "cases" / "red_flags.jsonl"
MAX_FALSE_POSITIVE_RATE = 0.01
MAX_P99_MS = 50.0


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Read one JSON case per line."""
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * pct // 100))
    return ordered[int(rank) - 1]


def evaluate(
    cases: list[dict[str, Any]],
    screen_fn: Callable[[str], RedFlagMatch | None] = screen,
) -> dict[str, Any]:
    """Score the cases.

    Args:
        cases: Rows with ``text``, ``expect_match`` and (when matching) ``rule_id``.
        screen_fn: The screen under test.

    Returns:
        Misses (expected but not caught or wrong rule), false positives, the
        ordinary-message false-positive rate, p99 time in ms and ``passed``.
    """
    misses: list[str] = []
    false_positives: list[str] = []
    timings: list[float] = []
    ordinary = 0
    for case in cases:
        started = time.perf_counter()
        match = screen_fn(case["text"])
        timings.append((time.perf_counter() - started) * 1000)
        if case["expect_match"]:
            if match is None or match.rule_id != case["rule_id"]:
                misses.append(case["text"])
        else:
            ordinary += 1
            if match is not None:
                false_positives.append(case["text"])
    rate = len(false_positives) / ordinary if ordinary else 0.0
    p99 = percentile(timings, 99)
    return {
        "cases": len(cases),
        "misses": misses,
        "false_positives": false_positives,
        "false_positive_rate": rate,
        "p99_ms": p99,
        "passed": not misses and rate <= MAX_FALSE_POSITIVE_RATE and p99 < MAX_P99_MS,
    }


def main() -> int:
    """Run the gate; exit 1 when it fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES)
    args = parser.parse_args()
    report = evaluate(load_cases(args.cases))
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
