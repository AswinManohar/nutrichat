"""The hard-fact inference eval's pure metrics, on synthetic scores (no model)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "eval" / "eval_hard_fact_inference.py"
_spec = importlib.util.spec_from_file_location("eval_hard_fact_inference", _PATH)
ev = importlib.util.module_from_spec(_spec)
sys.modules["eval_hard_fact_inference"] = ev
_spec.loader.exec_module(ev)

SHELLFISH = {"allergen_group": "shellfish"}
PEANUT = {"allergen_group": "peanut"}


def _pred(entry_type: str, value: dict, p: float | None) -> ev.Prediction:
    return ev.Prediction(entry_type, value, p)


def _exp(entry_type: str, value: dict) -> ev.Expected:
    return ev.Expected(type=entry_type, value=value)


def _case(expected: list[ev.Expected], split: str = "tune") -> ev.Case:
    return ev.Case(message="m", expected=expected, stratum="s", split=split)


@pytest.mark.parametrize(
    ("p", "band"),
    [
        (0.95, "accept"),
        (0.9, "accept"),
        (0.89, "ask"),
        (0.5, "ask"),
        (0.49, "drop"),
        (None, "ask"),
    ],
)
def test_band_of(p, band) -> None:
    assert ev.band_of(p, ask=0.5, accept=0.9) == band


def test_values_compare_after_normalisation() -> None:
    assert ev.matches(
        _pred("allergy", SHELLFISH, 0.9), _exp("allergy", dict(SHELLFISH))
    )
    assert not ev.matches(_pred("allergy", SHELLFISH, 0.9), _exp("allergy", PEANUT))
    assert not ev.matches(
        _pred("medication", {"name": "Warfarin"}, 0.9),
        _exp("allergy", SHELLFISH),
    )
    assert not ev.matches(_pred("allergy", {"bogus": 1}, 0.9), _exp("allergy", PEANUT))


def test_soft_predictions_match_on_kind_and_text() -> None:
    soft = _pred(ev.SOFT, {"kind": "dislike", "fact": "Dislikes Coriander"}, 0.9)

    assert ev.matches(soft, _exp(ev.SOFT, {"kind": "dislike", "contains": "coriander"}))
    assert not ev.matches(
        soft, _exp(ev.SOFT, {"kind": "like", "contains": "coriander"})
    )


def test_a_case_is_scored_per_type_and_band() -> None:
    expected = [_exp("allergy", SHELLFISH), _exp("medication", {"name": "Warfarin"})]
    predictions = [
        _pred("allergy", SHELLFISH, 0.95),  # accept, correct
        _pred("allergy", PEANUT, 0.7),  # ask, wrong
        _pred("medication", {"name": "Metformin"}, 0.2),  # dropped
    ]

    scored = ev.score_case(predictions, expected, 0.5, 0.9, 0.6)

    assert (scored.by_band["accept"].tp, scored.by_band["accept"].fp) == (1, 0)
    assert (scored.by_band["ask"].tp, scored.by_band["ask"].fp) == (0, 1)
    assert scored.by_type["allergy"].tp == 1 and scored.by_type["allergy"].fp == 1
    assert scored.by_type["medication"].fn == 1  # the dropped candidate is not a fp
    assert scored.by_type["medication"].fp == 0


def test_an_expected_fact_is_matched_once() -> None:
    expected = [_exp("allergy", SHELLFISH)]
    predictions = [_pred("allergy", SHELLFISH, 0.95), _pred("allergy", SHELLFISH, 0.95)]

    scored = ev.score_case(predictions, expected, 0.5, 0.9, 0.6)

    assert (scored.overall.tp, scored.overall.fp, scored.overall.fn) == (1, 1, 0)


def test_precision_recall_and_empty_cases() -> None:
    assert ev.precision(ev.Counts(tp=3, fp=1)) == 0.75
    assert ev.recall(ev.Counts(tp=3, fn=1)) == 0.75
    assert ev.precision(ev.Counts()) is None and ev.recall(ev.Counts()) is None


def test_soft_scoring_uses_its_own_threshold() -> None:
    expected = [_exp(ev.SOFT, {"kind": "dislike", "contains": "okra"})]
    low = [_pred(ev.SOFT, {"kind": "dislike", "fact": "Dislikes okra"}, 0.3)]
    high = [_pred(ev.SOFT, {"kind": "dislike", "fact": "Dislikes okra"}, 0.8)]

    assert ev.score_case(low, expected, 0.5, 0.9, 0.6).overall.fn == 1
    assert ev.score_case(high, expected, 0.5, 0.9, 0.6).overall.tp == 1


def test_band_recall_counts_hard_facts_only() -> None:
    expected = [_exp("allergy", SHELLFISH), _exp(ev.SOFT, {"contains": "okra"})]
    predictions = [_pred("allergy", SHELLFISH, 0.95)]

    scored = ev.score_case(predictions, expected, 0.5, 0.9, 0.6)

    assert ev.band_recall(scored, "accept") == 1.0
    assert ev.band_recall(scored, "ask") == 0.0


def test_brier_and_reliability_on_known_points() -> None:
    points = [(1.0, True), (0.0, False), (0.8, False), (0.2, True)]

    assert ev.brier(points) == pytest.approx((0 + 0 + 0.64 + 0.64) / 4)
    assert ev.brier([]) is None
    rows = ev.reliability(points, bins=5)
    by_low = {round(r["low"], 1): r for r in rows}
    assert by_low[0.8]["n"] == 2  # 0.8 and 1.0 (the top bin includes 1.0)
    assert by_low[0.8]["accuracy"] == 0.5
    assert by_low[0.2]["mean_p"] == pytest.approx(0.2)
    assert by_low[0.0]["accuracy"] == 0.0


def test_sweep_ranks_pairs_that_meet_the_precision_target_first() -> None:
    cases = [
        (_case([_exp("allergy", SHELLFISH)]), [_pred("allergy", SHELLFISH, 0.92)]),
        (_case([]), [_pred("allergy", PEANUT, 0.85)]),  # a false positive at 0.85
        (
            _case([_exp("medication", {"name": "Warfarin"})]),
            [_pred("medication", {"name": "Warfarin"}, 0.6)],
        ),
    ]

    rows = ev.sweep(cases, (0.5,), (0.8, 0.9), 0.6, 0.98)

    assert [(r["accept"], r["meets_target"]) for r in rows] == [
        (0.9, True),
        (0.8, False),
    ]
    best = rows[0]
    assert best["accept_precision"] == 1.0
    assert best["hard_recall"] == 1.0
    assert best["accept_recall"] == 0.5
    assert rows[1]["accept_precision"] == 0.5


def test_sweep_skips_pairs_with_ask_above_accept() -> None:
    rows = ev.sweep([(_case([]), [])], (0.9,), (0.8, 0.95), 0.6, 0.98)

    assert [(r["ask"], r["accept"]) for r in rows] == [(0.9, 0.95)]


def test_a_missing_dataset_says_so_and_stops(tmp_path, capsys) -> None:
    code = ev.main(["--dataset", str(tmp_path / "missing.jsonl")])

    assert code == 2
    assert "nothing to evaluate" in capsys.readouterr().out


def test_report_runs_from_saved_predictions_without_a_model(tmp_path, capsys) -> None:
    dataset = tmp_path / "cases.jsonl"
    cases = [
        _case([_exp("allergy", SHELLFISH)], "tune"),
        _case([_exp("allergy", PEANUT)], "holdout"),
    ]
    dataset.write_text("\n".join(c.model_dump_json() for c in cases))
    saved = tmp_path / "preds.json"
    saved.write_text(
        json.dumps(
            [
                [{"type": "allergy", "value": SHELLFISH, "probability": 0.95}],
                [{"type": "allergy", "value": PEANUT, "probability": 0.7}],
            ]
        )
    )

    code = ev.main(["--dataset", str(dataset), "--load-predictions", str(saved)])

    out = capsys.readouterr().out
    assert code == 0
    assert "Brier score" in out and "Threshold sweep on tune" in out
    assert "Holdout (1 cases)" in out


def test_asking_on_a_hedged_case_is_not_an_error() -> None:
    """A hedged statement may be read back, but must not be saved silently."""
    guess = [ev.Prediction("allergy", {"allergen_group": "milk"}, 0.7)]
    sure = [ev.Prediction("allergy", {"allergen_group": "milk"}, 0.95)]

    assert ev.score_case(guess, [], 0.5, 0.9, 0.6, ask_ok=True).overall.fp == 0
    assert ev.score_case(sure, [], 0.5, 0.9, 0.6, ask_ok=True).overall.fp == 1
    assert ev.score_case(guess, [], 0.5, 0.9, 0.6).overall.fp == 1


def test_generated_rows_load_as_cases() -> None:
    row = {
        "message": "I think I might be lactose intolerant",
        "expected": [],
        "stratum": "hedged",
        "split": "tune",
        "ask_ok": True,
        "seed_id": "allergy-hedged-01",
        "type": "allergy",
        "source": "generated",
    }
    assert ev.Case.model_validate(row).ask_ok is True
