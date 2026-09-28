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
    (1013, "Blueberry juice"),
    (1014, "Blueberry syrup"),
    # Lower fdc_id than the NFS row, so the old -fdc_id tie-break picked it.
    (1015, "Cheese, fontina"),
    (1016, "Cheese, NFS"),
    # Regression fixture for issue #38: bare "toast" must resolve to toasted
    # bread, not a dish that merely contains the word "toast".
    (1017, "Shrimp toast"),
    (1018, "Bread, white, toasted"),
    (1019, "French toast, NFS"),
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


def test_bare_noun_prefers_generic_nfs_entry(fixture_db: Path) -> None:
    """A bare noun resolves to FDC's generic entry, not an arbitrary specific.

    "cheese" ties "Cheese, NFS" and "Cheese, fontina" on confidence (1.0
    each -- a one-word query is covered by any description containing it),
    head purity (both {cheese}) and description coverage (both 0.5), so the
    order fell through to fdc_id and returned fontina.
    """
    match = usda_local.lookup("cheese")
    assert match is not None
    assert match.description == "Cheese, NFS"


def test_head_matching_rows_enter_a_truncated_pool(fixture_db: Path) -> None:
    """Head-noun matches are retrieved even when bm25 fills the pool.

    With ``pool_size=1`` the FTS pool holds a single bm25 winner, which for
    a one-word query favours whichever short description repeats the term --
    "Rice flour, white, unenriched" or "Beans and white rice" -- over the
    "Rice, ..." entries the ranking would actually prefer. The supplement
    puts a head match back in contention.
    """
    match = usda_local.lookup("rice", pool_size=1)
    assert match is not None
    assert match.description.startswith("Rice,")


def test_bare_toast_resolves_to_toasted_bread_not_shrimp_toast(
    fixture_db: Path,
) -> None:
    """Regression for issue #38: "toast" must not resolve to "Shrimp toast".

    "toast" is a preparation of bread, not an FDC head noun on its own, so
    plain lexical matching picked whatever short description contained the
    literal word -- a dim-sum dish the user never named.
    """
    match = usda_local.lookup("toast")
    assert match is not None
    assert match.description == "Bread, white, toasted"
    assert match.description != "Shrimp toast"


def test_eggs_and_toast_entity_resolves_to_toasted_bread(fixture_db: Path) -> None:
    """The "toast" entity from "2 eggs and toast" must not pick up shrimp."""
    match = usda_local.lookup("toast")
    assert match is not None
    assert "shrimp" not in match.description.lower()


def test_french_toast_is_not_rewritten_to_bread(fixture_db: Path) -> None:
    """The preparation synonym must not clobber a real compound dish."""
    match = usda_local.lookup("french toast")
    assert match is not None
    assert match.description == "French toast, NFS"


def test_normalize_preparation_rewrites_bare_toast() -> None:
    from backend.agent.tools.usda_match import _normalize_preparation

    assert _normalize_preparation("toast") == "bread, toasted"
    assert _normalize_preparation("2 eggs and toast") == "2 eggs and bread, toasted"


def test_normalize_preparation_leaves_compound_dishes_alone() -> None:
    from backend.agent.tools.usda_match import _normalize_preparation

    assert _normalize_preparation("french toast") == "french toast"
    assert _normalize_preparation("melba toast") == "melba toast"
    assert _normalize_preparation("cinnamon toast") == "cinnamon toast"
    assert _normalize_preparation("french fries") == "french fries"


def test_normalize_preparation_does_not_touch_substrings() -> None:
    from backend.agent.tools.usda_match import _normalize_preparation

    # "toasted" contains "toast" but is a different word -- must not match.
    assert _normalize_preparation("toasted almonds") == "toasted almonds"


def test_generic_rank_only_fires_when_all_modifiers_are_generic() -> None:
    from backend.agent.tools.usda_match import _generic_rank

    assert _generic_rank("Cheese, NFS") == 1.0
    assert _generic_rank("Apple, raw") == 1.0
    assert _generic_rank("Cheese, fontina") == 0.0
    assert _generic_rank("Rice, white, cooked") == 0.0
    # FDC's second generic convention, "NS as to <dimension>" -- as common as
    # NFS (255 rows vs 251) but a free-text phrase rather than a token.
    assert _generic_rank("Lamb, NS as to cut") == 1.0
    assert _generic_rank("Chicken, NS as to part") == 1.0
    # Still strict: a real modifier alongside the marker disqualifies it.
    assert _generic_rank("Corn, NS as to form, cooked") == 0.0
    assert _generic_rank("Yogurt, Greek, NS as to type of milk, plain") == 0.0
    # No modifier at all is not "generic" -- "Peanut butter" must not be
    # promoted over an entry the query specified more precisely.
    assert _generic_rank("Peanut butter") == 0.0


def test_search_foods_ranks_toasted_bread_above_shrimp_toast(fixture_db: Path) -> None:
    results = usda_local.search_foods("toast")
    assert results, "expected at least one result"
    assert results[0].name == "Bread, white, toasted"


def test_search_foods_respects_limit(fixture_db: Path) -> None:
    results = usda_local.search_foods("rice", limit=2)
    assert len(results) <= 2


def test_search_foods_empty_for_gibberish(fixture_db: Path) -> None:
    results = usda_local.search_foods("zzxxqqvv12345")
    assert results == []


def test_search_foods_raises_when_db_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USDA_DB_PATH", "/nonexistent/path/to.sqlite3")
    with pytest.raises(usda_local.FoodDbUnavailable):
        usda_local.search_foods("rice")


def test_get_food_returns_scaled_ready_nutrients(fixture_db: Path) -> None:
    match = usda_local.lookup("toast")
    assert match is not None
    food = usda_local.get_food(match.fdc_id)
    assert food is not None
    assert food.fdc_id == match.fdc_id
    assert food.kcal_per_100g == _SAMPLE_MACROS["kcal"]
    assert food.protein_g_per_100g == _SAMPLE_MACROS["protein_g"]
    assert food.nutrients_per_100g["Energy"]["amount"] == 130.0


def test_get_food_returns_none_for_unknown_fdc_id(fixture_db: Path) -> None:
    assert usda_local.get_food(999999) is None


def test_get_food_raises_when_db_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USDA_DB_PATH", "/nonexistent/path/to.sqlite3")
    with pytest.raises(usda_local.FoodDbUnavailable):
        usda_local.get_food(1001)


# ---------------------------------------------------------------------------
# T022a: regression cases from #51 against the REAL bundled database (not
# the small fixture above), for both automatic matching (lookup) and search.
# Skipped if the bundled DB isn't present in this checkout.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_db() -> Iterator[None]:
    """Point usda_local at the real bundled database, restoring env after."""
    if not usda_local.is_available():
        pytest.skip("bundled usda_fdc.sqlite3 not present in this checkout")
    usda_local._local = usda_local.threading.local()
    yield
    usda_local._local = usda_local.threading.local()


def test_regression_51_rice_lookup(real_db: None) -> None:
    match = usda_local.lookup("rice")
    assert match is not None
    assert "rice crackers" not in match.description.lower()


def test_regression_51_toast_lookup(real_db: None) -> None:
    match = usda_local.lookup("toast")
    assert match is not None
    assert "shrimp toast" not in match.description.lower()


def test_regression_51_blueberries_lookup(real_db: None) -> None:
    match = usda_local.lookup("blueberries")
    assert match is not None
    assert "blueberry juice" not in match.description.lower()


def test_regression_51_water_lookup(real_db: None) -> None:
    match = usda_local.lookup("water")
    assert match is not None
    assert "tonic water" not in match.description.lower()


@pytest.mark.xfail(
    reason=(
        "known miss after #51's port (T001/T022a): automatic matching for "
        "bare 'chicken breast' still picks 'Chicken breast, roll, "
        "oven-roasted' (a deli product) over plain chicken breast, because "
        "the roll variant's shorter/more literal description out-scores it "
        "on _rank_key. The real cut ('Chicken, breast, boneless, skinless, "
        "raw') IS in the top-5 search pool (see the passing search-mode "
        "case for the same query), so this is a ranking gap, not a pool "
        "gap. Left as a known miss per the 2026-09-24 decision not to "
        "retune the ranker for this feature; tracked, not silently lost."
    ),
    strict=True,
)
def test_regression_51_chicken_breast_lookup(real_db: None) -> None:
    match = usda_local.lookup("chicken breast")
    assert match is not None
    assert "roll" not in match.description.lower()


def test_regression_51_chicken_breast_in_top5_search(real_db: None) -> None:
    """Even though automatic matching misses (see xfail above), plain
    chicken breast is reachable via search within the top 5 results."""
    hits = usda_local.search_foods("chicken breast", limit=5)
    names = [h.name.lower() for h in hits]
    assert any("roll" not in n and "chicken" in n and "breast" in n for n in names)
