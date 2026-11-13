"""The reply-guard eval's cases and pure scoring code (no model, no network)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from backend.safety.reply_guard import GuardVerdict
from backend.safety.tables import load_tables

_PATH = Path(__file__).resolve().parents[1] / "eval" / "eval_reply_guard.py"
_spec = importlib.util.spec_from_file_location("eval_reply_guard", _PATH)
ev = importlib.util.module_from_spec(_spec)
sys.modules["eval_reply_guard"] = ev
_spec.loader.exec_module(ev)

CASES = ev.load_cases()


def test_cases_are_valid_and_cover_the_required_kinds() -> None:
    assert len(CASES) >= 30
    assert any(c.violation for c in CASES) and any(not c.violation for c in CASES)
    assert {c.layer for c in CASES} == {"lexical", "usda", "glide", "none"}
    assert any(c.live_only for c in CASES)
    assert any(not c.entries for c in CASES)
    assert any(e.state == "pending" for c in CASES for e in c.entries)


async def test_layers_one_and_two_decide_every_offline_case_as_expected() -> None:
    tables = load_tables()

    outcomes = [
        await ev.run_case(c, tables, live=False) for c in CASES if not c.live_only
    ]

    assert [(o.id, o.expected, o.got) for o in outcomes if o.expected != o.got] == []
    by_id = {c.id: c for c in CASES}
    assert [o.id for o in outcomes if o.layer != by_id[o.id].layer] == []


def _outcome(expected: bool, got: bool, layer: str = "lexical", layer3: bool = False):
    return ev.Outcome(
        id="x", expected=expected, got=got, layer=layer, reached_layer3=layer3
    )


def test_score_reports_precision_recall_layers_and_layer3_share() -> None:
    result = ev.score(
        [
            _outcome(True, True),
            _outcome(True, False, "none", True),
            _outcome(False, True, "usda"),
            _outcome(False, False, "none"),
        ]
    )

    assert (result.true_positives, result.false_positives, result.false_negatives) == (
        1,
        1,
        1,
    )
    assert result.precision == 0.5 and result.recall == 0.5
    assert result.by_layer == {"lexical": 1, "none": 2, "usda": 1}
    assert result.layer3_share == 0.25


def test_score_of_nothing_is_perfect_and_empty() -> None:
    result = ev.score([])

    assert (result.precision, result.recall, result.layer3_share) == (1.0, 1.0, 0.0)


def test_a_clean_reply_with_a_food_phrase_reaches_layer_three() -> None:
    case = next(c for c in CASES if c.id == "g28-vegan-ok")
    verdict = GuardVerdict(food_phrases=["lentil curry"])

    assert ev.outcome_of(case, verdict, load_tables()).reached_layer3


def test_a_patient_without_constraints_never_reaches_layer_three() -> None:
    case = next(c for c in CASES if c.id == "g35-no-constraints")
    verdict = GuardVerdict(food_phrases=["toast"])

    assert not ev.outcome_of(case, verdict, load_tables()).reached_layer3


def test_duplicate_case_ids_are_rejected(tmp_path) -> None:
    path = tmp_path / "cases.jsonl"
    line = CASES[0].model_dump_json()
    path.write_text(line + "\n" + line + "\n")

    with pytest.raises(ValueError, match="duplicate"):
        ev.load_cases(path)
