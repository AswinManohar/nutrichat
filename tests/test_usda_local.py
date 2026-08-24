"""Tests for the SQLite read path in ``backend.agent.tools.usda_local``."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.agent.tools import usda_local
from backend.agent.tools.usda_match import _confidence
from backend.scripts.build_usda_db import create_schema, insert_food_row

_ROWS: list[tuple[int, str]] = [
    (1001, "Rice, white, long-grain, regular, raw, enriched"),
    (1002, "Rice flour, white, unenriched"),
    (1003, "Beans and white rice"),
    (1004, "Chicken, breast, boneless, skinless, raw"),
    (1005, "Lunchmeat, chicken breast, sliced"),
    (1006, "Bananas, raw"),
    (1007, "Banana split"),
    (1008, "Blueberries, raw"),
    (1009, "Oatmeal, NFS"),
    (1010, "Bread, oatmeal"),
    (1011, "Rice, brown, long-grain, cooked"),
    (1012, "Chicken curry"),
]

_SAMPLE_MACROS = {
    "kcal": 130.0,
    "protein_g": 2.7,
    "carbs_g": 28.0,
    "fat_g": 0.3,
    "fiber_g": 0.4,
    "sugar_g": 0.1,
    "sat_fat_g": 0.1,
}

_SAMPLE_NUTRIENTS = {
    "Energy": {"amount": 130.0, "unit": "kcal"},
    "Protein": {"amount": 2.7, "unit": "g"},
    "Sodium, Na": {"amount": 1.0, "unit": "mg"},
}


def _build_db(path: Path) -> None:
    """Create a small fixture SQLite database with FTS populated."""
    conn = sqlite3.connect(str(path))
    try:
        create_schema(conn)
        for fdc_id, description in _ROWS:
            insert_food_row(
                conn,
                fdc_id,
                description,
                "sr_legacy_food",
                None,
                None,
                _SAMPLE_MACROS,
                _SAMPLE_NUTRIENTS,
            )
        conn.execute(
            "INSERT INTO food_fts(rowid, description) "
            "SELECT fdc_id, description FROM food"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def fixture_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Build a fixture database and point ``usda_local`` at it."""
    db_path = tmp_path / "usda_fdc.sqlite3"
    _build_db(db_path)
    monkeypatch.setenv("USDA_DB_PATH", str(db_path))
    usda_local._local = usda_local.threading.local()
    yield db_path
    usda_local._local = usda_local.threading.local()


def test_white_rice_picks_plain_rice_not_flour_or_beans(fixture_db: Path) -> None:
    match = usda_local.lookup("white rice")
    assert match is not None
    assert match.description == "Rice, white, long-grain, regular, raw, enriched"
    assert match.description != "Rice flour, white, unenriched"
    assert match.description != "Beans and white rice"


def test_chicken_breast_picks_plain_not_lunchmeat(fixture_db: Path) -> None:
    match = usda_local.lookup("chicken breast")
    assert match is not None
    assert match.description == "Chicken, breast, boneless, skinless, raw"


def test_banana_picks_plain_not_split(fixture_db: Path) -> None:
    match = usda_local.lookup("banana")
    assert match is not None
    assert match.description == "Bananas, raw"


def test_match_confidence_equals_confidence_of_chosen(fixture_db: Path) -> None:
    match = usda_local.lookup("white rice")
    assert match is not None
    assert match.match_confidence == _confidence("white rice", match.description)


def test_candidates_capped_and_best_first(fixture_db: Path) -> None:
    match = usda_local.lookup("rice", max_candidates=2)
    assert match is not None
    assert len(match.candidates) <= 2
    assert match.candidates[0] == match.description


def test_lookup_is_deterministic(fixture_db: Path) -> None:
    first = usda_local.lookup("white rice")
    second = usda_local.lookup("white rice")
    assert first is not None and second is not None
    assert first.fdc_id == second.fdc_id


@pytest.mark.parametrize("query", ["", "!!!"])
def test_empty_tokens_returns_none(fixture_db: Path, query: str) -> None:
    assert usda_local.lookup(query) is None


def test_substring_rescue_finds_blueberries(fixture_db: Path) -> None:
    match = usda_local.lookup("berries")
    assert match is not None
    assert match.description == "Blueberries, raw"


def test_nutrients_round_trip_per_100g(fixture_db: Path) -> None:
    match = usda_local.lookup("banana")
    assert match is not None
    assert match.nutrients_per_100g == _SAMPLE_NUTRIENTS
    assert match.macros_per_100g == _SAMPLE_MACROS


def test_concurrent_lookups_are_thread_safe(fixture_db: Path) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(lambda _: usda_local.lookup("white rice"), range(8))
        )
    assert all(result is not None for result in results)
    fdc_ids = {result.fdc_id for result in results}
    assert len(fdc_ids) == 1
