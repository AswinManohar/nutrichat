"""Read path for the bundled SQLite copy of USDA FoodData Central.

Replaces live FDC API calls with lookups against a 15 MB, read-only SQLite
database shipped alongside the backend (13,694 foods). This module owns
retrieval and ranking only -- it returns a plain, dependency-free
``LocalMatch`` and leaves gram scaling and conversion into the API-facing
``USDAResult`` model to ``usda.py``, which imports this module (never the
other way around, to avoid a circular import).

The ranking strategy here was chosen empirically against the eval set and
must not be changed without re-running ``eval/gate.py``'s food_identity
category. Beware how coarse that signal is: the category is 22 cases, so
one case is 4.5pp, and the strategy originally shipped on a 14-case set
where it beat its runner-up by a single case (78.6% vs 71.4%). For finer
resolution score ``eval/cases/food_identity_expanded.jsonl`` (176 cases,
0.57pp each), where this ranker measures 88.1% recall@1 -- ahead of BM25,
Gemini embeddings, and RRF fusions of either (see EXPANDED_NOTES.md), and
chosen over an LLM reranker on 2026-09-24.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import backend
from backend.agent.tools.usda_match import (
    _MATCH_STOPWORDS,
    _confidence,
    _description_coverage,
    _generic_rank,
    _head_purity,
    _normalize_preparation,
    _tokenize,
)

_DB_PATH_ENV_VAR = "USDA_DB_PATH"

_local = threading.local()


@dataclass(frozen=True)
class LocalMatch:
    """One resolved USDA food match from the local SQLite database.

    Attributes:
        fdc_id: FDC food id of the chosen match.
        description: FDC description of the chosen match.
        match_confidence: Query-word coverage of the chosen description,
            per ``_confidence`` -- the real coverage score, never boosted.
        candidates: Descriptions of the top-ranked candidates (best first),
            capped at ``max_candidates``.
        macros_per_100g: Headline macros (kcal, protein_g, carbs_g, fat_g,
            fiber_g, sugar_g, sat_fat_g), per 100 g, unscaled.
        nutrients_per_100g: Full nutrient map, name -> {"amount", "unit"},
            per 100 g, unscaled.
    """

    fdc_id: int
    description: str
    match_confidence: float
    candidates: list[str] = field(default_factory=list)
    macros_per_100g: dict[str, float] = field(default_factory=dict)
    nutrients_per_100g: dict[str, dict] = field(default_factory=dict)


def database_path() -> Path:
    """Resolve the path to the bundled USDA SQLite database.

    Honors the ``USDA_DB_PATH`` environment variable when set (used by
    tests to point at a fixture database), otherwise resolves to
    ``backend/data/usda_fdc.sqlite3`` relative to the installed package --
    never relative to the current working directory, since the process may
    be launched from anywhere.

    Returns:
        Path to the SQLite database file (may not exist).
    """
    override = os.environ.get(_DB_PATH_ENV_VAR)
    if override:
        return Path(override)
    return Path(backend.__file__).parent / "data" / "usda_fdc.sqlite3"


def is_available() -> bool:
    """Check whether the local USDA database exists and can be opened.

    Returns:
        True if the database file exists and a read-only connection can be
        opened against it. Never raises -- any failure is treated as
        unavailable.
    """
    path = database_path()
    if not path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            conn.execute("SELECT 1 FROM food LIMIT 1")
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        return False


def _get_connection() -> sqlite3.Connection:
    """Return this thread's read-only connection, opening one if needed.

    ``usda_lookup_batch`` fans out lookups across worker threads via
    ``asyncio.to_thread``, so several threads hit SQLite concurrently. Each
    thread gets its own connection (rather than sharing one with
    ``check_same_thread=False``) so reads never contend on a single
    connection object. The database file is immutable at runtime, so
    concurrent read-only connections need no additional locking.

    Returns:
        An open, read-only sqlite3 connection scoped to the current thread.
    """
    conn = getattr(_local, "conn", None)
    path = getattr(_local, "path", None)
    current_path = database_path()
    if conn is None or path != current_path:
        conn = sqlite3.connect(f"file:{current_path}?mode=ro", uri=True)
        _local.conn = conn
        _local.path = current_path
    return conn


def _fts_query(tokens: set[str]) -> str:
    """Build a quoted, prefix-matching FTS5 MATCH expression from tokens.

    Every token is quoted so punctuation in a food name can never produce a
    malformed FTS5 query, and tokens are sorted first so the resulting
    query string -- and therefore bm25 ranking -- is deterministic.

    Args:
        tokens: Tokenized query words.

    Returns:
        An FTS5 MATCH expression, e.g. ``'"chicken"* OR "rice"*'``.
    """
    return " OR ".join(f'"{token}"*' for token in sorted(tokens))


def _fts_candidates(
    conn: sqlite3.Connection, tokens: set[str], pool_size: int
) -> dict[int, tuple[str, float]]:
    """Fetch FTS5 candidates ranked by bm25.

    Args:
        conn: Open read-only connection.
        tokens: Tokenized query words.
        pool_size: Max rows to fetch.

    Returns:
        Dict of fdc_id -> (description, bm25_rank). Empty if the query
        tokenizes to a malformed FTS5 expression or no rows match.
    """
    query = _fts_query(tokens)
    try:
        rows = conn.execute(
            """
            SELECT f.fdc_id, f.description, bm25(food_fts)
            FROM food_fts
            JOIN food f ON f.fdc_id = food_fts.rowid
            WHERE food_fts MATCH ?
            ORDER BY bm25(food_fts)
            LIMIT ?
            """,
            (query, pool_size),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {fdc_id: (description, bm25) for fdc_id, description, bm25 in rows}


def _raw_words(text_value: str) -> set[str]:
    """Lowercase, strip punctuation, drop stopwords -- no singularizing.

    Used only for the substring rescue's LIKE patterns. ``_tokenize``
    singularizes ("berries" -> "berry"), which is correct for set-overlap
    scoring but wrong for a literal substring search against raw
    description text: "berry" is not a substring of "blueberries" ("berry"
    needs a trailing y where "blueberries" has "berrie...s"), while the
    unsingularized "berries" is. Substring rescue exists precisely to catch
    this kind of mid-word match, so it must search with the query's actual
    word forms.

    Args:
        text_value: Free text to tokenize.

    Returns:
        Set of lowercased, punctuation-stripped words, stopwords removed.
    """
    raw = re.sub(r"[^\w\s]", " ", text_value.lower()).split()
    return {t for t in raw if t not in _MATCH_STOPWORDS}


def _substring_rescue(
    conn: sqlite3.Connection,
    food_name: str,
    candidates: dict[int, tuple[str, float]],
    pool_size: int,
) -> None:
    """Supplement a thin FTS candidate pool with LIKE substring matches.

    FTS5 prefix matching cannot find a token that appears mid-word (e.g.
    "berries" inside "Blueberries"), so when the FTS pool is under
    ``pool_size`` this backfills with plain substring search. Mutates
    ``candidates`` in place, using ``setdefault`` so rows already ranked by
    bm25 keep their real rank and only new rows get the placeholder rank
    of 0.0.

    Args:
        conn: Open read-only connection.
        food_name: The user's original free-text food name.
        candidates: Candidate map to supplement in place.
        pool_size: Target pool size; supplement stops once reached.
    """
    if len(candidates) >= pool_size:
        return
    for token in sorted(_raw_words(food_name)):
        remaining = pool_size - len(candidates)
        if remaining <= 0:
            break
        rows = conn.execute(
            "SELECT fdc_id, description FROM food WHERE description LIKE ? LIMIT ?",
            (f"%{token}%", remaining),
        ).fetchall()
        for fdc_id, description in rows:
            candidates.setdefault(fdc_id, (description, 0.0))


def _head_match_supplement(
    conn: sqlite3.Connection,
    food_name: str,
    candidates: dict[int, tuple[str, float]],
    limit: int,
) -> None:
    """Guarantee entries whose *head noun is the query* are in the pool.

    Ranking prefers a candidate whose head segment the query names outright
    (see ``_head_purity``), but it can only choose among what bm25 retrieved,
    and for a one-word query bm25 is the wrong instrument: it favours short
    descriptions where the term is a large fraction of the text, so "rice"
    returned "Rice crackers", "Rice cake" and "Rice paper" while "Rice,
    white, long-grain, regular, enriched, cooked" -- the entry the ranking
    would have picked -- never entered the pool at all. No scoring change can
    fix a candidate that was never a candidate.

    Rows are taken shortest-description-first so that, when the head has more
    matching entries than ``limit``, the ones that survive are the least
    qualified (most generic) rather than an arbitrary slice: the database
    holds far more rows beginning "Cheese," than the limit allows, and
    without the ordering "Cheese, NFS" lost its place to named varieties.

    Mutates ``candidates`` in place, using ``setdefault`` so rows already
    ranked by bm25 keep their real rank and only new rows get the
    placeholder rank of 0.0.

    Args:
        conn: Open read-only connection.
        food_name: The user's original free-text food name.
        candidates: Candidate map to supplement in place.
        limit: Max head-matching rows to add.
    """
    head = food_name.strip().lower()
    rows = conn.execute(
        """
        SELECT fdc_id, description FROM food
        WHERE lower(description) = ? OR lower(description) LIKE ?
        ORDER BY length(description)
        LIMIT ?
        """,
        (head, f"{head},%", limit),
    ).fetchall()
    for fdc_id, description in rows:
        candidates.setdefault(fdc_id, (description, 0.0))


def _rank_key(
    query: str, description: str, bm25_rank: float, fdc_id: int
) -> tuple[float, float, float, float, float, int]:
    """Build the descending sort key used to pick the best candidate.

    Args:
        query: The user's free-text food name.
        description: Candidate FDC description.
        bm25_rank: bm25 rank for this candidate (lower is better in SQLite,
            so it is negated for a descending sort).
        fdc_id: Candidate's FDC id, the final deterministic tie-break.

    Returns:
        Tuple sorted descending: (confidence, head_purity,
        description_coverage, generic_rank, -bm25_rank, -fdc_id).
    """
    return (
        _confidence(query, description),
        _head_purity(query, description),
        _description_coverage(query, description),
        _generic_rank(description),
        -bm25_rank,
        -fdc_id,
    )


def _load_row(conn: sqlite3.Connection, fdc_id: int) -> tuple[dict[str, float], dict]:
    """Load macros and decompressed nutrients for one food, per 100 g.

    Args:
        conn: Open read-only connection.
        fdc_id: FDC id to load.

    Returns:
        Tuple of (macros_per_100g, nutrients_per_100g). Neither is scaled
        by quantity -- that is the caller's (``usda.py``'s) job.
    """
    row = conn.execute(
        """
        SELECT kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sat_fat_g,
               nutrients_z
        FROM food WHERE fdc_id = ?
        """,
        (fdc_id,),
    ).fetchone()
    (
        kcal,
        protein_g,
        carbs_g,
        fat_g,
        fiber_g,
        sugar_g,
        sat_fat_g,
        nutrients_z,
    ) = row
    macros = {
        "kcal": kcal,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "fiber_g": fiber_g,
        "sugar_g": sugar_g,
        "sat_fat_g": sat_fat_g,
    }
    nutrients = json.loads(zlib.decompress(nutrients_z))
    return macros, nutrients


def lookup(
    food_name: str, *, pool_size: int = 25, max_candidates: int = 3
) -> LocalMatch | None:
    """Resolve a free-text food name against the bundled USDA database.

    Retrieves a candidate pool via FTS5 prefix search (backfilled with
    substring search when the pool is thin, and always supplemented with
    rows whose head noun is the query), ranks candidates by confidence,
    then head purity, then description coverage, then generic rank, then
    bm25, then fdc_id, and returns the top match with its macros and
    nutrients per 100 g.

    Args:
        food_name: User-facing free-text food name.
        pool_size: Max candidates to retrieve before ranking.
        max_candidates: Max number of runner-up descriptions to return.

    Returns:
        The best ``LocalMatch``, or None if the query tokenizes to nothing
        or no candidates are found.
    """
    food_name = _normalize_preparation(food_name)
    tokens = _tokenize(food_name)
    if not tokens:
        return None

    conn = _get_connection()
    candidates = _fts_candidates(conn, tokens, pool_size)
    _substring_rescue(conn, food_name, candidates, pool_size)
    _head_match_supplement(conn, food_name, candidates, pool_size)
    if not candidates:
        return None

    ranked = sorted(
        candidates.items(),
        key=lambda item: _rank_key(food_name, item[1][0], item[1][1], item[0]),
        reverse=True,
    )

    best_fdc_id, (best_description, _) = ranked[0]
    macros, nutrients = _load_row(conn, best_fdc_id)

    return LocalMatch(
        fdc_id=best_fdc_id,
        description=best_description,
        match_confidence=_confidence(food_name, best_description),
        candidates=[desc for _, (desc, _) in ranked[:max_candidates]],
        macros_per_100g=macros,
        nutrients_per_100g=nutrients,
    )
