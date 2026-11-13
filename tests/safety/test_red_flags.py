from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from backend.safety import red_flags, tables
from backend.safety.red_flags import (
    HARD_FALLBACK_TEXT,
    RedFlagsUnavailable,
    fallback_text,
    screen,
)

_SHIPPED = Path(__file__).resolve().parents[2] / "src/backend/config/clinical"

_TWO_RULES = """version: 1
reviewed_by: "test"
fallback_unavailable_text: "fallback from file"
rules:
  - id: first
    label: "First"
    patterns: ['\\bpanic\\b']
    response: "first response"
  - id: second
    label: "Second"
    patterns: ['\\bpanic\\b', '\\bworry\\b']
    response: "second response"
"""


@pytest.fixture
def clinical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "clinical"
    shutil.copytree(_SHIPPED, target)
    monkeypatch.setattr(tables, "clinical_dir", lambda directory=None: target)
    monkeypatch.setattr(red_flags, "clinical_dir", lambda directory=None: target)
    return target


def _write(path: Path, text: str, bump_ns: int = 5_000_000_000) -> None:
    path.write_text(text)
    stamp = path.stat().st_mtime_ns + bump_ns
    os.utime(path, ns=(stamp, stamp))


def test_match_anywhere_in_a_longer_message(clinical: Path) -> None:
    message = "Log my lunch: rice and dal. " * 20 + "Also I stopped my insulin. Thanks"

    match = screen(message)

    assert match is not None
    assert match.rule_id == "stopped_insulin"
    assert match.response
    assert len(match.rules_version) == 64


def test_matching_is_case_insensitive(clinical: Path) -> None:
    assert screen("I WANT TO DIE").rule_id == "self_harm"


def test_ordinary_message_passes(clinical: Path) -> None:
    assert screen("2 eggs and toast with insulin-friendly oats") is None


def test_first_rule_in_file_order_wins(clinical: Path) -> None:
    _write(clinical / "red_flags.yaml", _TWO_RULES)

    assert screen("I worry and panic").rule_id == "first"
    assert screen("I worry").rule_id == "second"


def test_edit_is_picked_up_without_restart(clinical: Path) -> None:
    _write(clinical / "red_flags.yaml", _TWO_RULES)
    before = screen("panic")
    _write(
        clinical / "red_flags.yaml",
        _TWO_RULES.replace("panic", "alarm"),
        bump_ns=10_000_000_000,
    )

    after = screen("alarm")

    assert screen("panic") is None
    assert after is not None
    assert after.rules_version != before.rules_version


@pytest.mark.parametrize(
    "content", ["rules: [unclosed", "version: 1\n", "rules: not-a-list"]
)
def test_invalid_file_raises(clinical: Path, content: str) -> None:
    _write(clinical / "red_flags.yaml", content)

    with pytest.raises(RedFlagsUnavailable):
        screen("hello")


def test_invalid_pattern_raises(clinical: Path) -> None:
    _write(clinical / "red_flags.yaml", _TWO_RULES.replace("\\bpanic\\b", "(["))

    with pytest.raises(RedFlagsUnavailable):
        screen("hello")


def test_missing_file_raises(clinical: Path) -> None:
    (clinical / "red_flags.yaml").unlink()

    with pytest.raises(RedFlagsUnavailable):
        screen("hello")


def test_recovers_when_the_file_is_fixed(clinical: Path) -> None:
    _write(clinical / "red_flags.yaml", "rules: [unclosed")
    with pytest.raises(RedFlagsUnavailable):
        screen("hello")

    _write(clinical / "red_flags.yaml", _TWO_RULES, bump_ns=10_000_000_000)

    assert screen("panic").rule_id == "first"


def test_broken_allergen_file_does_not_affect_screening(clinical: Path) -> None:
    _write(clinical / "allergen_groups.yaml", "groups: [unclosed")

    assert screen("I want to die").rule_id == "self_harm"
    with pytest.raises(tables.TablesUnavailable):
        tables.load_tables()


def test_broken_red_flags_does_not_affect_other_tables(clinical: Path) -> None:
    _write(clinical / "red_flags.yaml", "rules: [unclosed")

    with pytest.raises(tables.TablesUnavailable, match="red_flags.yaml"):
        tables.load_red_flags()
    # load_tables loads every file, so it fails too; the allergen file alone
    # still loads through the shared per-file loader.
    digest, _ = tables._load_file(
        clinical / "allergen_groups.yaml", tables.AllergenGroups
    )
    assert len(digest) == 64


def test_fallback_text_from_file_or_constant(clinical: Path) -> None:
    _write(clinical / "red_flags.yaml", _TWO_RULES.replace("panic", "(["))
    assert fallback_text() == "fallback from file"

    _write(clinical / "red_flags.yaml", "rules: [unclosed", bump_ns=10_000_000_000)
    assert fallback_text() == HARD_FALLBACK_TEXT

    (clinical / "red_flags.yaml").unlink()
    assert fallback_text() == HARD_FALLBACK_TEXT


def test_ten_kilobyte_message_is_screened_quickly(clinical: Path) -> None:
    screen("warm up")
    message = ("I had rice and dal with a little insulin-free chutney. " * 300)[:10_000]

    started = time.perf_counter()
    result = screen(message)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert result is None
    assert elapsed_ms < 50
