from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from backend.safety.tables import TablesUnavailable, load_tables

_SHIPPED = Path(__file__).resolve().parents[2] / "src/backend/config/clinical"


@pytest.fixture
def clinical(tmp_path: Path) -> Path:
    target = tmp_path / "clinical"
    shutil.copytree(_SHIPPED, target)
    return target


def test_shipped_tables_load() -> None:
    tables = load_tables()

    assert "peanut" in tables.allergen_groups.groups
    assert tables.red_flags.rules
    assert tables.texture_rules.levels[0] == "liquid"
    assert set(tables.hashes) == {
        "allergen_groups",
        "drug_food_interactions",
        "diet_rules",
        "texture_rules",
        "physical_rules",
        "condition_limits",
        "red_flags",
    }
    assert all(len(h) == 64 for h in tables.hashes.values())


def test_hash_changes_when_a_file_is_edited(clinical: Path) -> None:
    before = load_tables(clinical)
    path = clinical / "condition_limits.yaml"
    path.write_text(path.read_text() + "\n# edited\n")
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 1_000_000))

    after = load_tables(clinical)

    assert after.hashes["condition_limits"] != before.hashes["condition_limits"]
    assert after.hashes["red_flags"] == before.hashes["red_flags"]


def test_file_is_reread_only_when_mtime_changes(clinical: Path) -> None:
    first = load_tables(clinical)
    path = clinical / "condition_limits.yaml"
    stamp = path.stat().st_mtime_ns
    path.write_text(path.read_text().replace("high blood pressure", "hypertension"))
    os.utime(path, ns=(stamp, stamp))

    assert load_tables(clinical).hashes == first.hashes

    os.utime(path, ns=(stamp + 5_000_000_000, stamp + 5_000_000_000))
    reloaded = load_tables(clinical)
    assert reloaded.hashes["condition_limits"] != first.hashes["condition_limits"]
    assert reloaded.condition_limits.conditions["hypertension"].label == "hypertension"


def test_invalid_yaml_raises(clinical: Path) -> None:
    (clinical / "red_flags.yaml").write_text("rules: [unclosed")

    with pytest.raises(TablesUnavailable, match="red_flags.yaml"):
        load_tables(clinical)


def test_unknown_field_raises(clinical: Path) -> None:
    path = clinical / "physical_rules.yaml"
    path.write_text(path.read_text() + "surprise: true\n")

    with pytest.raises(TablesUnavailable, match="physical_rules.yaml"):
        load_tables(clinical)


def test_bad_red_flag_regex_raises(clinical: Path) -> None:
    path = clinical / "red_flags.yaml"
    path.write_text(path.read_text().replace("\\binsulin\\b.{0,30}", "(unclosed"))

    with pytest.raises(TablesUnavailable):
        load_tables(clinical)


def test_missing_file_raises(clinical: Path) -> None:
    (clinical / "allergen_groups.yaml").unlink()

    with pytest.raises(TablesUnavailable, match="allergen_groups.yaml"):
        load_tables(clinical)
