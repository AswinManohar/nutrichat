"""Pure parts of the hard-fact case generator (no model call)."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from backend.safety import profile

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "gen_hard_fact_cases", _ROOT / "eval" / "gen_hard_fact_cases.py"
)
gen = importlib.util.module_from_spec(_spec)
sys.modules["gen_hard_fact_cases"] = gen
_spec.loader.exec_module(gen)

HARD_TYPES = {
    "allergy",
    "diagnosis",
    "medication",
    "physical_limitation",
    "nutrient_limit",
}
SEED_FILE = _ROOT / "eval" / "cases" / "hard_fact_seeds.jsonl"


def _seed(seed_id: str = "allergy-clear-01", **kw) -> gen.Seed:
    fields = {
        "seed_id": seed_id,
        "message": "I am allergic to shellfish.",
        "expected": [{"type": "allergy", "value": {"allergen_group": "shellfish"}}],
        "stratum": "clear_first_person",
        "type": "allergy",
    }
    fields.update(kw)
    return gen.Seed(**fields)


def test_split_is_deterministic_and_roughly_80_20() -> None:
    assert gen.split_of("a-1") == gen.split_of("a-1")
    splits = Counter(gen.split_of(f"seed-{i}") for i in range(2000))
    assert set(splits) == {"tune", "holdout"}
    assert 0.15 < splits["holdout"] / 2000 < 0.25


def test_paraphrases_share_the_seed_split_and_label() -> None:
    seed = _seed()
    rows = gen.build_rows(seed, ["i'm allergic to shellfish", "Shellfish: allergic"])
    assert [r["source"] for r in rows] == ["seed", "generated", "generated"]
    assert {r["split"] for r in rows} == {gen.split_of(seed.seed_id)}
    assert all(r["expected"] == seed.expected for r in rows)
    assert all(r["stratum"] == seed.stratum and r["type"] == "allergy" for r in rows)


def test_build_rows_drops_blank_repeat_and_seed_copies() -> None:
    rows = gen.build_rows(_seed(), ["", "  ", "I AM allergic to shellfish.", "x", "X"])
    assert [r["message"] for r in rows] == ["I am allergic to shellfish.", "x"]


def test_ask_ok_is_carried_to_paraphrases() -> None:
    rows = gen.build_rows(_seed(expected=[], ask_ok=True), ["maybe I am"])
    assert all(r["ask_ok"] is True for r in rows)
    assert "ask_ok" not in gen.build_rows(_seed(), ["x"])[0]


def test_refuses_to_overwrite_the_reviewed_file(tmp_path: Path) -> None:
    reviewed = tmp_path / "reviewed.jsonl"
    with pytest.raises(gen.OverwriteRefused):
        gen.check_out_path(reviewed, reviewed)
    with pytest.raises(gen.OverwriteRefused):
        gen.check_out_path(gen.REVIEWED)
    gen.check_out_path(tmp_path / "draft.jsonl", reviewed)


def test_main_refuses_reviewed_path() -> None:
    with pytest.raises(SystemExit):
        gen.main(["--out", str(gen.REVIEWED), "--dry-run"])


def test_plan_counts_and_dry_run_calls_no_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    seeds = [_seed(f"allergy-clear-{i:02d}") for i in range(10)]
    plan = gen.make_plan(seeds, 5)
    assert plan.model_calls == 10 and plan.rows == 60
    assert sum(plan.by_split.values()) == 60
    assert plan.by_type == {"allergy": 60}

    path = tmp_path / "seeds.jsonl"
    path.write_text("".join(s.model_dump_json() + "\n" for s in seeds))
    out = tmp_path / "out.jsonl"

    async def boom(*_a, **_k):
        raise AssertionError("dry run must not call the model")

    monkeypatch.setattr(gen, "generate", boom)
    assert gen.main(["--seeds", str(path), "--out", str(out), "--dry-run"]) == 0
    assert "estimated model calls: 10" in capsys.readouterr().out
    assert not out.exists()


def test_duplicate_seed_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "seeds.jsonl"
    line = _seed().model_dump_json() + "\n"
    path.write_text(line * 2)
    with pytest.raises(ValueError, match="duplicate"):
        gen.load_seeds(path)


def test_seed_file_covers_every_type_and_stratum() -> None:
    seeds = gen.load_seeds(SEED_FILE)
    assert len(seeds) >= 450
    cells = Counter((s.type, s.stratum) for s in seeds)
    assert {t for t, _ in cells} == HARD_TYPES
    assert len({st for _, st in cells}) == 9
    assert min(cells.values()) >= 10
    positive = {"clear_first_person", "correction", "buried_in_meal_log"}
    for seed in seeds:
        assert bool(seed.expected) == (seed.stratum in positive), seed.seed_id
        assert seed.ask_ok == (seed.stratum == "hedged")


def test_seed_expected_values_fit_the_entry_models() -> None:
    models = {
        "allergy": profile.AllergyValue,
        "diagnosis": profile.DiagnosisValue,
        "medication": profile.MedicationValue,
        "physical_limitation": profile.PhysicalLimitationValue,
        "nutrient_limit": profile.NutrientLimitValue,
    }
    for line in SEED_FILE.read_text().splitlines():
        record = json.loads(line)
        for fact in record["expected"]:
            assert fact["type"] == record["type"]
            models[fact["type"]].model_validate(fact["value"])
