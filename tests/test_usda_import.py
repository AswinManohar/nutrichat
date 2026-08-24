"""Tests for the USDA FoodData Central SQLite importer.

Exercises the pure nutrient-resolution and macro-promotion logic plus a
round-trip through the schema helpers against an in-memory SQLite database.
None of these tests touch the real 481 MB FDC zip.
"""

from __future__ import annotations

import json
import sqlite3
import zlib

from backend.scripts.build_usda_db import (
    create_schema,
    insert_food_row,
    promote_macros,
    resolve_nutrients,
)

# nutrient_id -> (name, unit_name), mirroring nutrient.csv rows used in tests.
_NUTRIENT_META: dict[int, tuple[str, str]] = {
    1003: ("Protein", "G"),
    1004: ("Total lipid (fat)", "G"),
    1005: ("Carbohydrate, by difference", "G"),
    1008: ("Energy", "KCAL"),
    1062: ("Energy", "KJ"),
    1063: ("Energy (Atwater General Factors)", "KCAL"),
    1064: ("Energy (Atwater Specific Factors)", "KCAL"),
    1079: ("Fiber, total dietary", "G"),
    1114: ("Vitamin D (D2 + D3)", "UG"),
    2000: ("Total Sugars", "G"),
    1258: ("Fatty acids, total saturated", "G"),
}


def test_energy_dedup_kcal_wins_kj_after() -> None:
    """kcal id 1008 first, then kJ id 1062 -- kcal value must survive."""
    rows = [(1008, 597.0), (1062, 2500.0)]
    nutrients = resolve_nutrients(rows, _NUTRIENT_META)
    assert nutrients["Energy"] == {"amount": 597.0, "unit": "kcal"}


def test_energy_dedup_kj_first_then_kcal() -> None:
    """kJ id 1062 first, then kcal id 1008 -- kcal must still win."""
    rows = [(1062, 2500.0), (1008, 597.0)]
    nutrients = resolve_nutrients(rows, _NUTRIENT_META)
    assert nutrients["Energy"] == {"amount": 597.0, "unit": "kcal"}


def test_atwater_fallback_when_no_plain_energy() -> None:
    """A food with only an Atwater energy row populates kcal from it."""
    rows = [(1063, 639.0), (1003, 25.0)]
    nutrients = resolve_nutrients(rows, _NUTRIENT_META)
    macros = promote_macros(nutrients)
    assert macros["kcal"] == 639.0


def test_macro_map_promotion_missing_defaults_to_zero() -> None:
    """Promoted macros map correctly; a missing nutrient defaults to 0.0."""
    rows = [
        (1008, 597.0),
        (1003, 25.0),
        (1004, 50.0),
        # Carbohydrate deliberately absent.
        (1079, 6.0),
        (2000, 10.0),
        (1258, 9.0),
    ]
    nutrients = resolve_nutrients(rows, _NUTRIENT_META)
    macros = promote_macros(nutrients)
    assert macros == {
        "kcal": 597.0,
        "protein_g": 25.0,
        "carbs_g": 0.0,
        "fat_g": 50.0,
        "fiber_g": 6.0,
        "sugar_g": 10.0,
        "sat_fat_g": 9.0,
    }


def test_unit_lowercasing() -> None:
    """Units from nutrient.csv are lowercased (UG -> ug, KCAL -> kcal)."""
    rows = [(1114, 2.5), (1008, 100.0)]
    nutrients = resolve_nutrients(rows, _NUTRIENT_META)
    assert nutrients["Vitamin D (D2 + D3)"]["unit"] == "ug"
    assert nutrients["Energy"]["unit"] == "kcal"


def test_nutrient_names_preserved_verbatim() -> None:
    """Nutrient names are stored exactly as in nutrient.csv, no normalizing."""
    rows = [(1114, 2.5)]
    nutrients = resolve_nutrients(rows, _NUTRIENT_META)
    assert "Vitamin D (D2 + D3)" in nutrients
    assert list(nutrients.keys()) == ["Vitamin D (D2 + D3)"]


def test_round_trip_in_memory_db() -> None:
    """Build a small in-memory DB via the helpers, read a row back."""
    conn = sqlite3.connect(":memory:")
    create_schema(conn)

    rows = [(1008, 597.0), (1062, 2500.0), (1003, 25.0)]
    nutrients = resolve_nutrients(rows, _NUTRIENT_META)
    macros = promote_macros(nutrients)

    insert_food_row(
        conn,
        fdc_id=324860,
        description="Peanut butter, smooth style, without salt",
        data_type="sr_legacy_food",
        food_category_id=12,
        publication_date="2021-10-28",
        macros=macros,
        nutrients=nutrients,
    )
    conn.execute(
        "INSERT INTO food_fts(rowid, description) "
        "SELECT fdc_id, description FROM food"
    )
    conn.commit()

    row = conn.execute(
        "SELECT description, kcal, protein_g, nutrients_z FROM food "
        "WHERE fdc_id = 324860"
    ).fetchone()
    description, kcal, protein_g, blob = row
    assert description == "Peanut butter, smooth style, without salt"
    assert kcal == 597.0
    assert protein_g == 25.0

    decompressed = json.loads(zlib.decompress(blob))
    assert decompressed == nutrients

    fts_row = conn.execute(
        "SELECT f.description FROM food_fts "
        "JOIN food f ON f.fdc_id = food_fts.rowid "
        "WHERE food_fts MATCH 'peanut'"
    ).fetchone()
    assert fts_row[0] == "Peanut butter, smooth style, without salt"


def test_unparseable_and_empty_amount_rows_are_skipped() -> None:
    """Rows with empty or unparseable amounts are dropped, not raised."""
    raw_rows: list[tuple[str, str]] = [
        ("1008", "597.0"),
        ("1003", ""),
        ("1004", "not-a-number"),
    ]
    parsed: list[tuple[int, float]] = []
    for nutrient_id_str, amount_str in raw_rows:
        if not amount_str:
            continue
        try:
            amount = float(amount_str)
        except ValueError:
            continue
        parsed.append((int(nutrient_id_str), amount))

    nutrients = resolve_nutrients(parsed, _NUTRIENT_META)
    assert nutrients == {"Energy": {"amount": 597.0, "unit": "kcal"}}
