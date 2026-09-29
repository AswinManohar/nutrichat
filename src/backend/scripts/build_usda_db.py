"""Build (or verify) the bundled SQLite USDA FoodData Central database.

Streams ``food.csv``, ``food_nutrient.csv``, and ``nutrient.csv`` directly out
of the official FDC CSV zip release (never extracted to disk) and folds them
into a single-file SQLite database with an FTS5 description index. Touches no
Postgres and performs no async I/O -- this is an offline, single-threaded
batch job.

Build:
    PYTHONPATH=src uv run python -m backend.scripts.build_usda_db \\
        --zip ~/Downloads/FoodData_Central_csv_2026-04-30.zip \\
        --out src/backend/data/usda_fdc.sqlite3

Verify an already-built database:
    PYTHONPATH=src uv run python -m backend.scripts.build_usda_db \\
        --verify src/backend/data/usda_fdc.sqlite3
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
import zlib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from zipfile import ZipFile

from backend.agent.tools.usda_match import _ENERGY_KEYS, _MACRO_MAP, _energy_kcal

# Target FDC data types and the exact per-type row counts this importer must
# reproduce against the 2026-04-30 release. A mismatch means the release
# changed shape and the importer needs a human to look at it again.
_TARGET_DATA_TYPES: dict[str, int] = {
    "foundation_food": 469,
    "sr_legacy_food": 7793,
    "survey_fndds_food": 5432,
}
_EXPECTED_TOTAL = sum(_TARGET_DATA_TYPES.values())  # 13694

_SCHEMA_VERSION = 2

# Promoted macro columns that may be NULL (= FDC reports no value). ``kcal`` is
# excluded: it is resolved through the Atwater fallback chain and stays 0.0 only
# when FDC truly has no energy figure at all (verify() gates coverage on it).
_NULLABLE_MACROS = ("protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sat_fat_g")

_LOG_EVERY_ROWS = 2_000_000

_VERIFY_NUTRIENTS: dict[str, str] = {
    "Total Sugars": "g",
    "Vitamin C, total ascorbic acid": "mg",
    "Vitamin D (D2 + D3)": "ug",
    "Iron, Fe": "mg",
    "Calcium, Ca": "mg",
    "Vitamin B-12": "ug",
    "Sodium, Na": "mg",
    "Fatty acids, total saturated": "g",
    "Vitamin A, RAE": "ug",
}

_SPOT_CHECK_QUERIES: tuple[str, ...] = (
    "banana",
    "chicken breast",
    "white rice",
    "oatmeal",
    "greek yogurt",
    "chicken curry",
    "fried rice",
)

_SCHEMA_SQL = """
PRAGMA user_version = 2;

CREATE TABLE food (
    fdc_id           INTEGER PRIMARY KEY,
    description      TEXT NOT NULL,
    data_type        TEXT NOT NULL,
    food_category_id INTEGER,
    publication_date TEXT,
    kcal REAL NOT NULL,
    -- NULL = FDC has no value for this nutrient (unknown, NOT zero).
    protein_g REAL, carbs_g REAL, fat_g REAL, fiber_g REAL, sugar_g REAL,
    sat_fat_g REAL,
    nutrients_z    BLOB NOT NULL,
    nutrient_count INTEGER NOT NULL
);

CREATE VIRTUAL TABLE food_fts USING fts5(
    description, content='food', content_rowid='fdc_id',
    tokenize="unicode61 remove_diacritics 2"
);

-- Household serving weights (FDC food_portion): "1 cup" -> 244 g etc.
CREATE TABLE food_portion (
    fdc_id      INTEGER NOT NULL,
    seq_num     INTEGER,
    amount      REAL NOT NULL,
    unit        TEXT NOT NULL,
    description TEXT NOT NULL,
    modifier    TEXT NOT NULL,
    gram_weight REAL NOT NULL
);
CREATE INDEX food_portion_fdc_id ON food_portion (fdc_id);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def resolve_nutrients(
    rows: list[tuple[int, float]],
    nutrient_meta: dict[int, tuple[str, str]],
) -> dict[str, dict]:
    """Fold raw (nutrient_id, amount) rows for one food into a name-keyed map.

    Rows are sorted by ``nutrient_id`` before folding so the result is
    deterministic regardless of CSV row order. FDC lists two nutrients both
    named "Energy" (id 1008 in kcal, id 1062 in kJ); when the name repeats,
    the kcal entry always wins so calories are never inflated ~4.2x by a kJ
    value silently overwriting it.

    Args:
        rows: List of (nutrient_id, amount) tuples for a single food.
        nutrient_meta: Map of nutrient_id -> (name, unit_name) from
            nutrient.csv. Unit is stored lowercased.

    Returns:
        Dict of nutrient name -> {"amount": float, "unit": str}.
    """
    result: dict[str, dict] = {}
    for nutrient_id, amount in sorted(rows, key=lambda r: r[0]):
        meta = nutrient_meta.get(nutrient_id)
        if meta is None:
            continue
        name, unit = meta
        unit = unit.lower()
        if name in result and name == "Energy":
            existing_unit = result[name]["unit"]
            if existing_unit == "kcal":
                continue  # kcal already stored -- kJ (or another) never wins
            if unit != "kcal":
                continue  # neither is kcal yet -- keep the first non-kcal seen
        result[name] = {"amount": amount, "unit": unit}
    return result


def promote_macros(nutrients: dict[str, dict]) -> dict[str, float | None]:
    """Promote the 7 headline macro columns out of a resolved nutrient map.

    Args:
        nutrients: Name-keyed nutrient map as returned by
            ``resolve_nutrients``.

    Returns:
        Dict with keys kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g,
        sat_fat_g. A nutrient FDC does not report is ``None`` (unknown), never
        0.0. ``kcal`` is always a float, resolved via
        ``_energy_kcal``'s Atwater fallback chain rather than the plain
        "Energy" entry alone.
    """
    energy_raw = {
        key: (nutrients[key]["amount"], nutrients[key]["unit"])
        for key in _ENERGY_KEYS
        if key in nutrients
    }
    macros: dict[str, float | None] = {column: None for column in _MACRO_MAP.values()}
    for name, column in _MACRO_MAP.items():
        if column == "kcal":
            continue
        if name in nutrients:
            macros[column] = nutrients[name]["amount"]
    macros["kcal"] = _energy_kcal(energy_raw)
    return macros


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the food/food_fts/meta schema on a connection.

    Args:
        conn: Open sqlite3 connection, freshly created (empty database).
    """
    conn.executescript(_SCHEMA_SQL)


def insert_food_row(
    conn: sqlite3.Connection,
    fdc_id: int,
    description: str,
    data_type: str,
    food_category_id: int | None,
    publication_date: str | None,
    macros: dict[str, float | None],
    nutrients: dict[str, dict],
) -> None:
    """Insert one row into ``food`` (FTS index is populated separately).

    Args:
        conn: Open sqlite3 connection with the schema already created.
        fdc_id: FDC food id, primary key.
        description: Food description, verbatim from food.csv.
        data_type: One of the three target data_type values.
        food_category_id: Nullable FDC category id.
        publication_date: Nullable ISO date string.
        macros: Output of ``promote_macros``.
        nutrients: Output of ``resolve_nutrients``, compressed into
            ``nutrients_z``.
    """
    blob = zlib.compress(
        json.dumps(nutrients, separators=(",", ":"), sort_keys=True).encode(),
        9,
    )
    conn.execute(
        """
        INSERT INTO food (
            fdc_id, description, data_type, food_category_id,
            publication_date, kcal, protein_g, carbs_g, fat_g, fiber_g,
            sugar_g, sat_fat_g, nutrients_z, nutrient_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fdc_id,
            description,
            data_type,
            food_category_id,
            publication_date,
            macros["kcal"],
            macros["protein_g"],
            macros["carbs_g"],
            macros["fat_g"],
            macros["fiber_g"],
            macros["sugar_g"],
            macros["sat_fat_g"],
            blob,
            len(nutrients),
        ),
    )


def _find_zip_prefix(zf: ZipFile) -> str:
    """Discover the single top-level directory prefix inside the FDC zip.

    Args:
        zf: Open ZipFile.

    Returns:
        The top-level directory name, e.g. "FoodData_Central_csv_2026-04-30".

    Raises:
        ValueError: If the archive does not have exactly one top-level
            directory.
    """
    tops = {name.split("/", 1)[0] for name in zf.namelist() if "/" in name}
    if len(tops) != 1:
        raise ValueError(
            f"Expected exactly one top-level directory in the zip, found {tops!r}"
        )
    return next(iter(tops))


def _csv_reader(zf: ZipFile, member: str) -> csv.reader:
    """Open a streaming CSV reader over one zip member.

    Args:
        zf: Open ZipFile.
        member: Full path of the CSV member inside the archive.

    Returns:
        A csv.reader over a UTF-8 (BOM-stripped) text stream.
    """
    raw = zf.open(member)
    text_stream = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
    return csv.reader(text_stream)


def _load_nutrient_meta(zf: ZipFile, prefix: str) -> dict[int, tuple[str, str]]:
    """Load nutrient.csv into an id -> (name, unit_name) map.

    Args:
        zf: Open ZipFile.
        prefix: Top-level directory prefix inside the archive.

    Returns:
        Dict of nutrient id -> (name, unit_name), unit_name left as-is (the
        caller lowercases it).
    """
    reader = _csv_reader(zf, f"{prefix}/nutrient.csv")
    header = next(reader)
    idx = {col: i for i, col in enumerate(header)}
    meta: dict[int, tuple[str, str]] = {}
    for row in reader:
        nutrient_id = int(row[idx["id"]])
        name = row[idx["name"]]
        unit = row[idx["unit_name"]]
        meta[nutrient_id] = (name, unit)
    return meta


def _load_target_foods(
    zf: ZipFile, prefix: str
) -> dict[int, tuple[str, str, int | None, str | None]]:
    """Load food.csv, filtered to the target data_type set.

    Args:
        zf: Open ZipFile.
        prefix: Top-level directory prefix inside the archive.

    Returns:
        Dict of fdc_id -> (description, data_type, food_category_id,
        publication_date).

    Raises:
        ValueError: If the total row count does not equal 13694.
    """
    reader = _csv_reader(zf, f"{prefix}/food.csv")
    header = next(reader)
    idx = {col: i for i, col in enumerate(header)}
    foods: dict[int, tuple[str, str, int | None, str | None]] = {}
    for row in reader:
        data_type = row[idx["data_type"]]
        if data_type not in _TARGET_DATA_TYPES:
            continue
        fdc_id = int(row[idx["fdc_id"]])
        description = row[idx["description"]]
        category_raw = row[idx["food_category_id"]]
        food_category_id = int(category_raw) if category_raw else None
        publication_date = row[idx["publication_date"]] or None
        foods[fdc_id] = (description, data_type, food_category_id, publication_date)
    if len(foods) != _EXPECTED_TOTAL:
        raise ValueError(
            f"Expected exactly {_EXPECTED_TOTAL} target foods "
            f"({_TARGET_DATA_TYPES!r}), found {len(foods)}. The FDC release "
            "shape has changed -- update the expected counts deliberately."
        )
    return foods


def _load_portions(
    zf: ZipFile, prefix: str, target_ids: set[int]
) -> list[tuple[int, int | None, float, str, str, str, float]]:
    """Load food_portion.csv (household gram weights) for the target foods.

    Args:
        zf: Open ZipFile.
        prefix: Top-level directory prefix inside the archive.
        target_ids: fdc_ids of the foods being imported.

    Returns:
        Rows of (fdc_id, seq_num, amount, unit, description, modifier,
        gram_weight). Rows with a non-positive or unparseable gram weight are
        dropped. ``unit`` is the measure_unit name, or "" when FDC marks it
        "undetermined".
    """
    units: dict[str, str] = {}
    reader = _csv_reader(zf, f"{prefix}/measure_unit.csv")
    header = next(reader)
    idx = {col: i for i, col in enumerate(header)}
    for row in reader:
        name = row[idx["name"]]
        units[row[idx["id"]]] = "" if name == "undetermined" else name

    reader = _csv_reader(zf, f"{prefix}/food_portion.csv")
    header = next(reader)
    idx = {col: i for i, col in enumerate(header)}
    portions: list[tuple[int, int | None, float, str, str, str, float]] = []
    for row in reader:
        if not row or not row[idx["fdc_id"]].isdigit():
            continue  # blank/malformed line in the FDC export
        fdc_id = int(row[idx["fdc_id"]])
        if fdc_id not in target_ids:
            continue
        try:
            grams = float(row[idx["gram_weight"]])
            amount = float(row[idx["amount"]] or 1.0)
        except ValueError:
            continue
        if grams <= 0 or amount <= 0:
            continue
        seq_raw = row[idx["seq_num"]]
        portions.append(
            (
                fdc_id,
                int(float(seq_raw)) if seq_raw else None,
                amount,
                units.get(row[idx["measure_unit_id"]], ""),
                row[idx["portion_description"]].strip(),
                row[idx["modifier"]].strip(),
                grams,
            )
        )
    return portions


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file, streaming in chunks.

    Args:
        path: Path to the file to hash.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_name_from_zip(zip_path: Path) -> str:
    """Derive the FDC release identifier from the zip filename.

    Args:
        zip_path: Path to the source zip.

    Returns:
        The filename stem, e.g. "FoodData_Central_csv_2026-04-30".
    """
    return zip_path.stem


class BuildValidationError(Exception):
    """Raised when a freshly built database fails validation."""


def validate_built_db(db_path: Path, expected_portions: int | None = None) -> None:
    """Check a freshly built database before it may replace the live one.

    Runs SQLite's integrity check, the per-data_type row counts, FTS/food row
    parity, and (when given) the food_portion row count.

    Args:
        db_path: Path to the candidate database.
        expected_portions: Expected number of food_portion rows, or None to
            skip that check.

    Raises:
        BuildValidationError: If any check fails.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        result = conn.execute("PRAGMA integrity_check").fetchall()
        if result != [("ok",)]:
            raise BuildValidationError(f"integrity_check failed: {result[:3]!r}")
        for data_type, expected in _TARGET_DATA_TYPES.items():
            (actual,) = conn.execute(
                "SELECT COUNT(*) FROM food WHERE data_type = ?", (data_type,)
            ).fetchone()
            if actual != expected:
                raise BuildValidationError(
                    f"{data_type}: {actual} rows, expected {expected}"
                )
        (n_food,) = conn.execute("SELECT COUNT(*) FROM food").fetchone()
        (n_fts,) = conn.execute("SELECT COUNT(*) FROM food_fts_docsize").fetchone()
        if n_food != n_fts:
            raise BuildValidationError(f"FTS rows {n_fts} != food rows {n_food}")
        (n_portions,) = conn.execute("SELECT COUNT(*) FROM food_portion").fetchone()
        if expected_portions is not None and n_portions != expected_portions:
            raise BuildValidationError(
                f"food_portion: {n_portions} rows, expected {expected_portions}"
            )
        if expected_portions and n_portions == 0:
            raise BuildValidationError("food_portion is empty")
    except sqlite3.Error as exc:
        raise BuildValidationError(f"sqlite error during validation: {exc}") from exc
    finally:
        conn.close()


def build(zip_path: Path, out_path: Path) -> None:
    """Build the SQLite database from the FDC CSV zip release, atomically.

    The database is built into a sibling temp file, validated, and only then
    moved over ``out_path`` with ``os.replace`` (atomic on POSIX). Any failure
    -- unreadable archive, changed release shape, failed validation -- removes
    the temp file and leaves an existing ``out_path`` exactly as it was.

    Args:
        zip_path: Path to the FoodData_Central_csv_*.zip archive.
        out_path: Path of the database to create or replace.

    Raises:
        BuildValidationError: If the built database fails validation.
        ValueError: If the archive does not have the expected shape.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".building")
    if tmp_path.exists():
        tmp_path.unlink()
    try:
        expected_portions = _build_into(zip_path, tmp_path)
        validate_built_db(tmp_path, expected_portions)
        os.replace(tmp_path, out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    print(f"Built {out_path}", file=sys.stderr)


def _build_into(zip_path: Path, out_path: Path) -> int:
    """Write a fresh database to ``out_path`` (which must not exist).

    Args:
        zip_path: Path to the FoodData_Central_csv_*.zip archive.
        out_path: Path of the new database file.

    Returns:
        The number of food_portion rows written.
    """
    print(f"Hashing {zip_path} ...", file=sys.stderr)
    source_sha256 = _sha256_file(zip_path)

    with ZipFile(zip_path) as zf:
        prefix = _find_zip_prefix(zf)
        print(f"Archive prefix: {prefix}", file=sys.stderr)

        print("Loading nutrient.csv ...", file=sys.stderr)
        nutrient_meta = _load_nutrient_meta(zf, prefix)

        print("Loading food.csv (target data_types only) ...", file=sys.stderr)
        foods = _load_target_foods(zf, prefix)
        print(f"  kept {len(foods)} foods", file=sys.stderr)

        print("Loading food_portion.csv ...", file=sys.stderr)
        portions = _load_portions(zf, prefix, set(foods.keys()))
        print(f"  kept {len(portions)} portions", file=sys.stderr)

        print("Streaming food_nutrient.csv ...", file=sys.stderr)
        target_ids = set(foods.keys())
        rows_by_food: dict[int, list[tuple[int, float]]] = defaultdict(list)
        reader = _csv_reader(zf, f"{prefix}/food_nutrient.csv")
        header = next(reader)
        idx = {col: i for i, col in enumerate(header)}
        seen = 0
        for row in reader:
            seen += 1
            if seen % _LOG_EVERY_ROWS == 0:
                print(f"  ... {seen:,} food_nutrient rows scanned", file=sys.stderr)
            fdc_id = int(row[idx["fdc_id"]])
            if fdc_id not in target_ids:
                continue
            nutrient_id = int(row[idx["nutrient_id"]])
            amount_raw = row[idx["amount"]]
            if not amount_raw:
                continue
            try:
                amount = float(amount_raw)
            except ValueError:
                continue
            rows_by_food[fdc_id].append((nutrient_id, amount))
        print(f"  total food_nutrient rows scanned: {seen:,}", file=sys.stderr)

    conn = sqlite3.connect(str(out_path))
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    try:
        create_schema(conn)

        type_counts: dict[str, int] = defaultdict(int)
        for fdc_id in sorted(foods.keys()):
            description, data_type, food_category_id, publication_date = foods[fdc_id]
            nutrients = resolve_nutrients(rows_by_food.get(fdc_id, []), nutrient_meta)
            macros = promote_macros(nutrients)
            insert_food_row(
                conn,
                fdc_id,
                description,
                data_type,
                food_category_id,
                publication_date,
                macros,
                nutrients,
            )
            type_counts[data_type] += 1

        conn.executemany(
            "INSERT INTO food_portion (fdc_id, seq_num, amount, unit, "
            "description, modifier, gram_weight) VALUES (?, ?, ?, ?, ?, ?, ?)",
            portions,
        )
        conn.execute(
            "INSERT INTO food_fts(rowid, description) "
            "SELECT fdc_id, description FROM food"
        )

        nutrient_row_count = sum(len(v) for v in rows_by_food.values())
        meta_rows = {
            "source_zip_sha256": source_sha256,
            "fdc_release": _release_name_from_zip(zip_path),
            "schema_version": str(_SCHEMA_VERSION),
            "build_utc": datetime.now(UTC).isoformat(),
            "food_count": str(len(foods)),
            "nutrient_row_count": str(nutrient_row_count),
            "portion_count": str(len(portions)),
        }
        for data_type, count in type_counts.items():
            meta_rows[f"count_{data_type}"] = str(count)
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            list(meta_rows.items()),
        )
        conn.commit()

        print("Vacuuming ...", file=sys.stderr)
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()
    return len(portions)


def _spot_check(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[str]:
    """Return the top FTS matches for a query string.

    Args:
        conn: Open sqlite3 connection to the built database.
        query: Free-text FTS5 query.
        limit: Max number of results to return.

    Returns:
        List of matching descriptions, ranked by FTS relevance.
    """
    rows = conn.execute(
        """
        SELECT f.description FROM food_fts
        JOIN food f ON f.fdc_id = food_fts.rowid
        WHERE food_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [row[0] for row in rows]


def verify(db_path: Path) -> bool:
    """Run consistency checks against an already-built database.

    Args:
        db_path: Path to an existing sqlite3 database built by ``build``.

    Returns:
        True if all checks pass, False otherwise. Failures are printed to
        stderr with details.
    """
    ok = True
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        print("== Per-data_type counts ==", file=sys.stderr)
        for data_type, expected in _TARGET_DATA_TYPES.items():
            (actual,) = conn.execute(
                "SELECT COUNT(*) FROM food WHERE data_type = ?", (data_type,)
            ).fetchone()
            status = "OK" if actual == expected else "FAIL"
            print(
                f"  {data_type}: {actual} (expected {expected}) [{status}]",
                file=sys.stderr,
            )
            if actual != expected:
                ok = False

        print("== kcal coverage ==", file=sys.stderr)
        (total,) = conn.execute("SELECT COUNT(*) FROM food").fetchone()
        (nonzero,) = conn.execute("SELECT COUNT(*) FROM food WHERE kcal > 0").fetchone()
        share = nonzero / total if total else 0.0
        print(f"  {nonzero}/{total} foods have kcal > 0 ({share:.4%})", file=sys.stderr)
        if share < 0.98:
            print("  FAIL: kcal coverage below 98%", file=sys.stderr)
            ok = False
        zero_kcal = conn.execute(
            "SELECT description FROM food WHERE kcal = 0 LIMIT 10"
        ).fetchall()
        print("  sample zero-kcal foods:", file=sys.stderr)
        for row in zero_kcal:
            print(f"    - {row['description']}", file=sys.stderr)

        print("== Unknown (NULL) macro coverage ==", file=sys.stderr)
        for column in _NULLABLE_MACROS:
            (n_null,) = conn.execute(
                f"SELECT COUNT(*) FROM food WHERE {column} IS NULL"
            ).fetchone()
            print(f"  {column}: {n_null} foods unknown", file=sys.stderr)
        (n_portions,) = conn.execute("SELECT COUNT(*) FROM food_portion").fetchone()
        (n_with,) = conn.execute(
            "SELECT COUNT(DISTINCT fdc_id) FROM food_portion"
        ).fetchone()
        print(f"  food_portion: {n_portions} rows / {n_with} foods", file=sys.stderr)
        if n_portions == 0:
            print("  FAIL: no household portions", file=sys.stderr)
            ok = False

        print("== Required nutrients present ==", file=sys.stderr)
        for name, expected_unit in _VERIFY_NUTRIENTS.items():
            row = conn.execute(
                "SELECT nutrients_z FROM food " "WHERE nutrient_count > 0 LIMIT 200000"
            )
            found = False
            found_unit = None
            for (blob,) in row:
                nutrients = json.loads(zlib.decompress(blob))
                if name in nutrients:
                    found = True
                    found_unit = nutrients[name]["unit"]
                    break
            status = "OK" if found and found_unit == expected_unit else "FAIL"
            print(
                f"  {name!r}: found={found} unit={found_unit!r} "
                f"(expected {expected_unit!r}) [{status}]",
                file=sys.stderr,
            )
            if not (found and found_unit == expected_unit):
                ok = False

        print("== Nutrient count ==", file=sys.stderr)
        counts = [r[0] for r in conn.execute("SELECT nutrient_count FROM food")]
        print(f"  median nutrient_count per food: {median(counts)}", file=sys.stderr)

        print("== Spot checks ==", file=sys.stderr)
        for query in _SPOT_CHECK_QUERIES:
            matches = _spot_check(conn, query)
            print(f"  {query!r}:", file=sys.stderr)
            for match in matches:
                print(f"    - {match}", file=sys.stderr)
    finally:
        conn.close()
    return ok


def _default_out_path() -> Path:
    """Return the default output path relative to the repo layout."""
    return Path("src/backend/data/usda_fdc.sqlite3")


def main() -> None:
    """Parse CLI args and dispatch to build or verify."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--zip", type=Path, default=None, help="Path to the FDC CSV zip"
    )
    parser.add_argument(
        "--out", type=Path, default=_default_out_path(), help="Output sqlite3 path"
    )
    parser.add_argument(
        "--verify", type=Path, default=None, help="Verify an existing sqlite3 db"
    )
    args = parser.parse_args()

    if args.verify is not None:
        passed = verify(args.verify)
        if not passed:
            print("VERIFY FAILED", file=sys.stderr)
            sys.exit(1)
        print("VERIFY OK", file=sys.stderr)
        return

    if args.zip is None:
        parser.error("--zip is required to build a database (or pass --verify)")

    build(args.zip, args.out)


if __name__ == "__main__":
    main()
