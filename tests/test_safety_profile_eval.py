"""The safety-profile eval's cases and its pure scoring code (no model, no DB)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from backend.safety import profile
from backend.safety.tables import load_tables

_PATH = Path(__file__).resolve().parents[1] / "eval" / "eval_safety_profile.py"
_spec = importlib.util.spec_from_file_location("eval_safety_profile", _PATH)
ev = importlib.util.module_from_spec(_spec)
sys.modules["eval_safety_profile"] = ev
_spec.loader.exec_module(ev)

PATIENTS = ev.load_patients()
BY_ID = {p.id: p for p in PATIENTS}


def test_there_are_24_valid_patients_covering_every_entry_type() -> None:
    assert len(PATIENTS) == 24
    types = {f.type for p in PATIENTS for f in p.facts}
    assert types == set(profile.EntryType.__args__)
    assert any(f.state == "pending" for p in PATIENTS for f in p.facts)
    assert any(f.replaces for p in PATIENTS for f in p.facts)


def test_a_correction_supersedes_the_old_fact_only_once_learned() -> None:
    patient = BY_ID["sp23-correction"]

    assert [f.key for f in ev.live_facts(patient, 1)] == []  # retired, not yet replaced
    assert [f.key for f in ev.live_facts(patient, 2)] == ["a2"]


def test_the_expected_profile_is_recalled_in_full_with_no_pending_leak() -> None:
    tables = load_tables()
    results = [ev.check_patient(p, tables) for p in PATIENTS]

    assert [
        (r.id, r.missing, r.pending_leaks)
        for r in results
        if r.missing or r.pending_leaks
    ] == []
    assert sum(r.earlier_facts for r in results) > 0


def test_pending_facts_do_not_count_as_recalled_and_are_never_binding() -> None:
    result = ev.check_patient(BY_ID["sp22-pending-only"], load_tables())

    assert result.earlier_facts == 0 and result.pending_leaks == []


def test_score_profiles_reports_precision_and_recall_per_type() -> None:
    peanut = ev.to_entries(
        [
            ev.Fact(
                key="a",
                type="allergy",
                value={"allergen_group": "peanut"},
                state="confirmed",
                learned_in_session=1,
                said="x",
            )
        ]
    )
    milk = ev.to_entries(
        [
            ev.Fact(
                key="b",
                type="allergy",
                value={"allergen_group": "milk"},
                state="confirmed",
                learned_in_session=1,
                said="x",
            )
        ]
    )

    assert ev.score_profiles(peanut, peanut) == {
        "allergy": {"precision": 1.0, "recall": 1.0}
    }
    assert ev.score_profiles(peanut, milk) == {
        "allergy": {"precision": 0.0, "recall": 0.0}
    }
    assert ev.score_profiles(peanut, []) == {
        "allergy": {"precision": 1.0, "recall": 0.0}
    }


def test_live_mode_stops_until_extraction_is_wired() -> None:
    with pytest.raises(SystemExit, match="T073"):
        ev.run_live(PATIENTS)
