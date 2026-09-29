"""Issue #54: unknown nutrients stay unknown, household portions, atomic rebuild."""

from __future__ import annotations

import csv
import io
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.agent.orchestrator import _serialize_items
from backend.agent.tools import usda_local
from backend.agent.tools.meals import _is_junk, format_confirmation_card
from backend.agent.tools.usda import (
    USDAResult,
    _result_from_local,
    sum_known,
)
from backend.api.my_meals import _scaled_result
from backend.scripts import build_usda_db as build
from backend.scripts.build_usda_db import (
    BuildValidationError,
    create_schema,
    insert_food_row,
    promote_macros,
    resolve_nutrients,
)

_META = {
    1008: ("Energy", "KCAL"),
    1003: ("Protein", "G"),
    1079: ("Fiber, total dietary", "G"),
}


class _Entity:
    food_name = "x"
    qty_g = 200.0


def _result(**over: object) -> USDAResult:
    base = dict(
        fdc_id=1,
        food_name="Apple",
        qty_g=100.0,
        match_confidence=1.0,
        candidates=[],
        kcal=50.0,
        protein_g=1.0,
        carbs_g=10.0,
        fat_g=0.5,
        fiber_g=None,
        sugar_g=None,
        sat_fat_g=None,
        nutrients={},
    )
    base.update(over)
    return USDAResult(**base)  # type: ignore[arg-type]


# --------------------------- NULL propagation ------------------------------


def test_promote_macros_keeps_missing_as_none_and_real_zero_as_zero() -> None:
    nutrients = resolve_nutrients([(1008, 0.0), (1003, 0.0)], _META)
    macros = promote_macros(nutrients)
    assert macros["protein_g"] == 0.0  # measured zero stays zero
    assert macros["fiber_g"] is None  # absent stays unknown
    assert macros["kcal"] == 0.0


def test_null_macro_round_trips_through_sqlite_as_null() -> None:
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    macros = promote_macros(resolve_nutrients([(1008, 90.0), (1003, 2.0)], _META))
    insert_food_row(conn, 1, "Thing", "sr_legacy_food", None, None, macros, {})
    (fiber,) = conn.execute("SELECT fiber_g FROM food WHERE fdc_id=1").fetchone()
    assert fiber is None


def test_result_from_local_scales_known_and_keeps_unknown() -> None:
    match = usda_local.LocalMatch(
        fdc_id=1,
        description="Thing",
        match_confidence=1.0,
        macros_per_100g={
            "kcal": 100.0,
            "protein_g": 5.0,
            "carbs_g": 10.0,
            "fat_g": 1.0,
            "fiber_g": None,
            "sugar_g": None,
            "sat_fat_g": 0.0,
        },
    )
    r = _result_from_local(_Entity(), match)
    assert r.protein_g == 10.0
    assert r.fiber_g is None and r.sugar_g is None
    assert r.sat_fat_g == 0.0
    assert r.unknown_nutrients == ["fiber_g", "sugar_g"]


def test_json_wire_is_legacy_safe_but_names_unknowns() -> None:
    dumped = _result(protein_g=None).model_dump(mode="json")
    assert dumped["fiber_g"] == 0.0 and dumped["protein_g"] == 0.0
    assert dumped["sugar_g"] is None and dumped["sat_fat_g"] is None
    assert set(dumped["unknown_nutrients"]) == {
        "protein_g",
        "fiber_g",
        "sugar_g",
        "sat_fat_g",
    }
    # Python-mode dump (graph state) keeps the real None.
    assert _result().model_dump()["fiber_g"] is None


def test_serialize_items_marks_unknowns() -> None:
    item = _serialize_items([_result().model_dump()])[0]
    assert item["fiber_g"] == 0.0
    assert item["sugar_g"] is None
    assert "fiber_g" in item["unknown_nutrients"]


def test_totals_skip_unknowns() -> None:
    assert sum_known([1.0, None, 2.5]) == 3.5


def test_confirmation_card_shows_unknown_and_totals_skip_it() -> None:
    a = _result(fiber_g=3.0)
    b = _result(food_name="Pear", fiber_g=None)
    text = format_confirmation_card([a, b])
    assert "?g fiber" in text
    assert "3g fiber" in text.splitlines()[-3]  # total counts only the known 3 g


def test_is_junk_does_not_treat_unknown_as_evidence() -> None:
    # Unknown sugar / fiber / sat fat must not flag or exempt a food.
    assert _is_junk(_result(sugar_g=None, fiber_g=None, sat_fat_g=None)) is False
    assert _is_junk(_result(sugar_g=50.0, fiber_g=None)) is False  # fiber unknown
    assert _is_junk(_result(sugar_g=50.0, fiber_g=0.0)) is True


def test_saved_meal_scaling_preserves_unknown() -> None:
    stored = {
        "food_name": "Apple",
        "qty_g": 100.0,
        "kcal": 50.0,
        "protein_g": 1.0,
        "carbs_g": 10.0,
        "fat_g": 0.5,
        "fiber_g": 0.0,  # legacy-safe wire zero
        "sugar_g": None,
        "sat_fat_g": 0.2,
        "unknown_nutrients": ["fiber_g", "sugar_g"],
    }
    r = _scaled_result(stored, 200.0, 1.0)
    assert r.fiber_g is None and r.sugar_g is None
    assert r.sat_fat_g == 0.4 and r.kcal == 100.0


# --------------------------- portions lookup -------------------------------


@pytest.fixture
def portion_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "usda.sqlite3"
    conn = sqlite3.connect(path)
    create_schema(conn)
    insert_food_row(
        conn, 7, "Bread, white", "sr_legacy_food", None, None, promote_macros({}), {}
    )
    conn.executemany(
        "INSERT INTO food_portion VALUES (?,?,?,?,?,?,?)",
        [
            (7, 2, 1.0, "", "", "slice", 25.0),
            (7, 1, 2.0, "cup", "", "crumbs", 90.0),
            (7, 3, 1.0, "", "1 large roll", "", 60.0),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("USDA_DB_PATH", str(path))
    usda_local._local = usda_local.threading.local()
    yield path
    usda_local._local = usda_local.threading.local()


def test_portions_for_returns_ordered_labelled_weights(portion_db: Path) -> None:
    portions = usda_local.portions_for(7)
    assert [p.label for p in portions] == ["2 cup crumbs", "1 slice", "1 large roll"]
    assert [p.gram_weight for p in portions] == [90.0, 25.0, 60.0]
    assert portions[0].grams_per_unit == 45.0
    assert usda_local.portions_for(999) == []


def test_portions_for_tolerates_pre_v2_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE food (fdc_id INTEGER)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("USDA_DB_PATH", str(path))
    usda_local._local = usda_local.threading.local()
    assert usda_local.portions_for(1) == []
    usda_local._local = usda_local.threading.local()


# --------------------------- atomic rebuild --------------------------------


def _fake_zip(path: Path, portion_rows: list[list[str]] | None = None) -> None:
    def csv_text(rows: list[list[str]]) -> str:
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        return buf.getvalue()

    foods = [
        ["fdc_id", "data_type", "description", "food_category_id", "publication_date"]
    ]
    nutrient_rows = [["id", "fdc_id", "nutrient_id", "amount"]]
    n = 1
    for dtype in build._TARGET_DATA_TYPES:
        for i in range(build._TARGET_DATA_TYPES[dtype]):
            fid = n
            n += 1
            foods.append([str(fid), dtype, f"Food {fid}", "", ""])
            nutrient_rows.append([str(fid), str(fid), "1008", "100"])
    portions = [
        [
            "id",
            "fdc_id",
            "seq_num",
            "amount",
            "measure_unit_id",
            "portion_description",
            "modifier",
            "gram_weight",
        ],
        *(portion_rows or [["1", "1", "1", "1", "1000", "", "chopped", "120"]]),
    ]
    p = "FoodData_Central_csv_test"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{p}/food.csv", csv_text(foods))
        zf.writestr(f"{p}/food_nutrient.csv", csv_text(nutrient_rows))
        zf.writestr(
            f"{p}/nutrient.csv",
            csv_text([["id", "name", "unit_name"], ["1008", "Energy", "KCAL"]]),
        )
        zf.writestr(
            f"{p}/measure_unit.csv",
            csv_text([["id", "name"], ["1000", "cup"], ["9999", "undetermined"]]),
        )
        zf.writestr(f"{p}/food_portion.csv", csv_text(portions))


def _stamp(path: Path) -> bytes:
    return path.read_bytes()


def test_build_creates_db_with_portions_and_replaces_atomically(tmp_path: Path) -> None:
    zpath = tmp_path / "src.zip"
    _fake_zip(zpath)
    out = tmp_path / "usda.sqlite3"
    out.write_bytes(b"old")
    build.build(zpath, out)
    conn = sqlite3.connect(out)
    (n,) = conn.execute("SELECT COUNT(*) FROM food").fetchone()
    row = conn.execute(
        "SELECT unit, modifier, gram_weight FROM food_portion"
    ).fetchone()
    conn.close()
    assert n == build._EXPECTED_TOTAL
    assert row == ("cup", "chopped", 120.0)
    assert not list(tmp_path.glob("*.building"))


def test_failed_validation_leaves_old_db_intact(tmp_path: Path) -> None:
    zpath = tmp_path / "src.zip"
    _fake_zip(zpath)
    out = tmp_path / "usda.sqlite3"
    out.write_bytes(b"precious old db")
    with patch.object(
        build, "validate_built_db", side_effect=BuildValidationError("boom")
    ):
        with pytest.raises(BuildValidationError):
            build.build(zpath, out)
    assert _stamp(out) == b"precious old db"
    assert not list(tmp_path.glob("*.building"))


def test_bad_archive_leaves_old_db_intact(tmp_path: Path) -> None:
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("FoodData_Central_csv_test/nutrient.csv", "id,name,unit_name\n")
        zf.writestr(
            "FoodData_Central_csv_test/food.csv",
            "fdc_id,data_type,description,food_category_id,publication_date\n",
        )
        zf.writestr("FoodData_Central_csv_test/measure_unit.csv", "id,name\n")
        zf.writestr(
            "FoodData_Central_csv_test/food_portion.csv",
            "id,fdc_id,seq_num,amount,measure_unit_id,portion_description,modifier,gram_weight\n",
        )
        zf.writestr(
            "FoodData_Central_csv_test/food_nutrient.csv",
            "id,fdc_id,nutrient_id,amount\n",
        )
    out = tmp_path / "usda.sqlite3"
    out.write_bytes(b"precious old db")
    with pytest.raises(ValueError):
        build.build(zpath, out)
    assert _stamp(out) == b"precious old db"
    assert not list(tmp_path.glob("*.building"))


def test_validate_rejects_corrupt_or_short_db(tmp_path: Path) -> None:
    bad = tmp_path / "bad.sqlite3"
    conn = sqlite3.connect(bad)
    create_schema(conn)
    conn.commit()
    conn.close()
    with pytest.raises(BuildValidationError):
        build.validate_built_db(bad)  # zero foods: counts mismatch
