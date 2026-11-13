"""The red-flag eval's cases and pure scoring code (no model, no network)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from backend.safety.red_flags import RedFlagMatch

_PATH = Path(__file__).resolve().parents[1] / "eval" / "eval_red_flags.py"
_spec = importlib.util.spec_from_file_location("eval_red_flags", _PATH)
ev = importlib.util.module_from_spec(_spec)
sys.modules["eval_red_flags"] = ev
_spec.loader.exec_module(ev)


def _match(rule_id: str) -> RedFlagMatch:
    return RedFlagMatch(rule_id, rule_id, "r", "v")


def test_percentile_is_nearest_rank() -> None:
    values = [float(n) for n in range(1, 101)]

    assert ev.percentile(values, 99) == 99.0
    assert ev.percentile([], 99) == 0.0


def test_evaluate_reports_misses_wrong_rules_and_false_positives() -> None:
    cases = [
        {"text": "a", "expect_match": True, "rule_id": "x"},
        {"text": "b", "expect_match": True, "rule_id": "x"},
        {"text": "c", "expect_match": True, "rule_id": "x"},
        {"text": "d", "expect_match": False, "rule_id": None},
        {"text": "e", "expect_match": False, "rule_id": None},
    ]
    hits = {"a": _match("x"), "b": _match("other"), "d": _match("x")}

    report = ev.evaluate(cases, hits.get)

    assert report["misses"] == ["b", "c"]
    assert report["false_positives"] == ["d"]
    assert report["false_positive_rate"] == 0.5
    assert report["passed"] is False


def test_evaluate_passes_when_clean() -> None:
    cases = [
        {"text": "a", "expect_match": True, "rule_id": "x"},
        {"text": "b", "expect_match": False, "rule_id": None},
    ]

    assert ev.evaluate(cases, {"a": _match("x")}.get)["passed"] is True


def test_shipped_cases_pass_the_gate_against_the_shipped_rules() -> None:
    cases = ev.load_cases(ev.CASES)

    assert sum(not c["expect_match"] for c in cases) >= 300
    assert {c["rule_id"] for c in cases if c["expect_match"]} >= {
        "stopped_insulin",
        "self_harm",
        "severe_hypoglycemia",
    }
    assert ev.evaluate(cases)["passed"] is True
