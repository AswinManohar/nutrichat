"""Eval for the patient safety profile (spec 013, SC-003, FR-043).

Cases: ``eval/cases/safety_profile/patients.jsonl``, 24 synthetic patients. Each
has ``sessions`` (the patient's messages, one list per session), ``facts`` (the
hard-profile entry each statement should produce, the session that taught it,
the words that said it, its final state and, for a correction, the fact it
replaces) and ``probe`` (a question asked in a later session). The expected
profile at any session is derived from ``facts``; it is not stored twice.

Two modes:

* ``--offline`` needs no model and no database. It checks every case against the
  real ``EntryValue`` models, builds the expected profile after each session,
  renders the real hard block for the probe session and reports, per patient and
  overall:
    - recall of earlier-session facts: share of confirmed facts learned in an
      earlier session whose label is present in the block (SC-003, target 100%);
    - pending leaks: pending facts that appear anywhere but the "Awaiting
      confirmation" line (must be 0).
* ``--live`` replays the sessions through the extraction pipeline and scores the
  extracted profile against the expected one (precision and recall per entry
  type). The pipeline step is not wired yet: it arrives with the curator rewrite
  (tasks.md T073-T077), so live mode stops with a clear message until then. The
  scoring it will use (:func:`score_profiles`) is real and used by the offline
  self-check.

    PYTHONPATH=src python eval/eval_safety_profile.py --offline
    PYTHONPATH=src python eval/eval_safety_profile.py --live   # after T073

Exit code 1 when any offline check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.safety import profile
from backend.safety.tables import ClinicalTables, load_tables

CASES = Path(__file__).parent / "cases" / "safety_profile" / "patients.jsonl"
_EPOCH = datetime(2026, 11, 1, tzinfo=UTC)


class Fact(BaseModel):
    """One hard-profile entry a patient's statements should produce."""

    key: str
    type: profile.EntryType
    value: dict[str, Any]
    state: Literal["pending", "confirmed", "retired"]
    learned_in_session: int = Field(ge=1)
    said: str
    replaces: str | None = None

    model_config = ConfigDict(extra="forbid")


class Patient(BaseModel):
    """One synthetic patient: sessions, expected entries and a probe question."""

    id: str
    summary: str
    sessions: list[list[str]] = Field(min_length=1)
    facts: list[Fact] = Field(min_length=1)
    probe: str

    model_config = ConfigDict(extra="forbid")


def load_patients(path: Path = CASES) -> list[Patient]:
    """Read and validate the cases; every fact value must be a valid EntryValue.

    Raises:
        ValueError: On an invalid case, a duplicate id, a fact taught in a
            session that does not exist, or a ``replaces`` that names no fact.
    """
    patients = [
        Patient.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    if len({p.id for p in patients}) != len(patients):
        raise ValueError("duplicate patient ids")
    for patient in patients:
        keys = {f.key for f in patient.facts}
        for fact in patient.facts:
            profile.parse_value(fact.type, fact.value)
            if fact.learned_in_session > len(patient.sessions):
                raise ValueError(f"{patient.id}/{fact.key}: no such session")
            if fact.replaces is not None and fact.replaces not in keys:
                raise ValueError(f"{patient.id}/{fact.key}: unknown replaces")
    return patients


def live_facts(patient: Patient, after_session: int) -> list[Fact]:
    """Facts that exist after ``after_session``.

    A fact is live once learned, unless a fact learned by then replaces it.
    A retired fact with no replacement never counts as live.
    """
    learned = [f for f in patient.facts if f.learned_in_session <= after_session]
    replaced = {f.replaces for f in learned if f.replaces}
    return [
        f
        for f in learned
        if f.key not in replaced and not (f.state == "retired" and not f.replaces)
    ]


def to_entries(facts: list[Fact]) -> list[profile.HardEntry]:
    """Facts as hard entries, timestamped in order so ordering is stable."""
    entries = []
    for i, fact in enumerate(facts):
        at = _EPOCH + timedelta(seconds=i)
        state = "pending" if fact.state == "pending" else "confirmed"
        entries.append(
            profile.HardEntry(
                id=fact.key,
                type=fact.type,
                value=profile.parse_value(fact.type, fact.value),
                source="patient",
                state=state,
                created_at=at,
                created_by="patient",
                confirmed_at=at if state == "confirmed" else None,
            )
        )
    return entries


class PatientResult(BaseModel):
    """Offline result for one patient."""

    id: str
    earlier_facts: int
    recalled: int
    pending_leaks: list[str]
    missing: list[str]

    model_config = ConfigDict(extra="forbid")


def check_patient(patient: Patient, tables: ClinicalTables) -> PatientResult:
    """Recall of earlier-session facts and pending leaks for one patient.

    The probe is asked after the last session, so "earlier" is every fact
    learned in any session. Only confirmed facts must be recalled; a pending
    fact must appear only on the "Awaiting confirmation" line.
    """
    entries = to_entries(live_facts(patient, len(patient.sessions)))
    lines = profile.render_block(entries, tables).splitlines()
    awaiting = [ln for ln in lines if ln.startswith("- Awaiting confirmation")]
    binding = "\n".join(ln for ln in lines if ln not in awaiting).casefold()
    confirmed = [e for e in entries if e.state == "confirmed"]
    # Casefolded: diet settings and conditions render as lowercase lists.
    missing = [
        label
        for e in confirmed
        if (label := profile.label_for(e, tables)).casefold() not in binding
    ]
    leaks = [
        label
        for e in entries
        if e.state == "pending"
        and (label := profile.label_for(e, tables)).casefold() in binding
    ]
    return PatientResult(
        id=patient.id,
        earlier_facts=len(confirmed),
        recalled=len(confirmed) - len(missing),
        pending_leaks=leaks,
        missing=missing,
    )


def score_profiles(
    expected: list[profile.HardEntry], got: list[profile.HardEntry]
) -> dict[str, dict[str, float]]:
    """Precision and recall per entry type, matching on (type, value)."""

    def key(e: profile.HardEntry) -> str:
        value = json.dumps(e.value.model_dump(exclude_none=True), sort_keys=True)
        return f"{e.type}:{value}"

    want, have = {key(e) for e in expected}, {key(e) for e in got}
    per_type: dict[str, dict[str, float]] = defaultdict(dict)
    for entry_type in {k.split(":", 1)[0] for k in want | have}:
        w = {k for k in want if k.startswith(entry_type + ":")}
        h = {k for k in have if k.startswith(entry_type + ":")}
        hits = len(w & h)
        per_type[entry_type] = {
            "precision": hits / len(h) if h else 1.0,
            "recall": hits / len(w) if w else 1.0,
        }
    return dict(per_type)


def run_offline(patients: list[Patient]) -> int:
    """Print the offline report; return the exit code."""
    tables = load_tables()
    results = [check_patient(p, tables) for p in patients]
    total = sum(r.earlier_facts for r in results)
    recalled = sum(r.recalled for r in results)
    for r in results:
        flag = "ok " if r.recalled == r.earlier_facts and not r.pending_leaks else "BAD"
        print(
            f"{flag} {r.id}: recalled {r.recalled}/{r.earlier_facts}"
            + (f" missing={r.missing}" if r.missing else "")
            + (f" pending_leaks={r.pending_leaks}" if r.pending_leaks else "")
        )
    leaks = sum(len(r.pending_leaks) for r in results)
    print(
        f"\nrecall of earlier-session facts: {recalled}/{total} "
        f"({100 * recalled / total:.1f}%), pending leaks: {leaks}"
    )
    return 0 if recalled == total and leaks == 0 else 1


def run_live(patients: list[Patient]) -> int:
    """Replay the sessions through extraction and score the result (not wired)."""
    raise SystemExit(
        "live mode needs the typed hard-fact extraction (spec 013 T073-T077); "
        f"{len(patients)} cases are ready and score_profiles() is the scorer."
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="no model, no database")
    mode.add_argument("--live", action="store_true", help="replay through extraction")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--only", help="run one patient id")
    args = parser.parse_args(argv)
    patients = load_patients(args.cases)
    if args.only:
        patients = [p for p in patients if p.id == args.only]
        if not patients:
            parser.error(f"no patient {args.only!r}")
    return run_offline(patients) if args.offline else run_live(patients)


if __name__ == "__main__":
    sys.exit(main())
