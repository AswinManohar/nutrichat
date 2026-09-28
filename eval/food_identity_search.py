"""Offline eval: GET /foods/search top-5 hit rate over food_identity cases.

Spec 003, T022 (SC-004: top-5 hit rate >= 90%). Complements the existing
recall@1 scoring for `usda_local.lookup` (used to gate #51's port, T001) by
scoring `usda_local.search_foods` instead: for each case in
`eval/cases/food_identity_expanded.jsonl`, search the case's expected food
phrase (the `query` field -- not a whole meal sentence) with `limit=5` and
check whether any of the top 5 results is acceptable, by `acceptable_fdc_ids`
or by `acceptable_name_substrings` (case-insensitive substring of the
result's name).

Run directly against the checked-out bundled database:

    PYTHONPATH=src uv run python eval/food_identity_search.py
    PYTHONPATH=src uv run python eval/food_identity_search.py --limit 5 --verbose

Not wired into eval/gate.py (that harness scores the LLM pipeline over N
noisy runs; this is a deterministic, offline score against the local SQLite
DB, same spirit as the recall@1 number recorded for T001).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "src"))

from backend.agent.tools import usda_local  # noqa: E402

CASES_PATH = Path(__file__).parent / "cases" / "food_identity_expanded.jsonl"


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """Read the food_identity_expanded JSONL case file."""
    cases = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _is_acceptable(hit: usda_local.LocalFoodHit, case: dict) -> bool:
    """A hit is acceptable if it matches the case's id list or substrings."""
    if hit.fdc_id in case.get("acceptable_fdc_ids", []):
        return True
    name_lower = hit.name.lower()
    return any(
        sub.lower() in name_lower for sub in case.get("acceptable_name_substrings", [])
    )


def score_search(cases: list[dict], limit: int = 5) -> dict:
    """Score `usda_local.search_foods` top-`limit` hit rate over `cases`.

    Args:
        cases: Parsed food_identity_expanded rows.
        limit: How many search results count as "top" (SC-004 uses 5).

    Returns:
        Dict with `hit_rate` (0-1), `hits`, `total`, and `misses` (list of
        case dicts that missed, for reporting).
    """
    hits = 0
    misses: list[dict] = []
    for case in cases:
        query = case["query"]
        try:
            results = usda_local.search_foods(query, limit=limit)
        except usda_local.FoodDbUnavailable:
            misses.append({**case, "error": "food_db_unavailable"})
            continue
        if any(_is_acceptable(hit, case) for hit in results):
            hits += 1
        else:
            misses.append({**case, "top_results": [h.name for h in results]})
    total = len(cases)
    return {
        "hits": hits,
        "total": total,
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "misses": misses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5, help="Top-N cutoff (SC-004: 5)")
    parser.add_argument("--verbose", action="store_true", help="Print each miss")
    args = parser.parse_args()

    if not usda_local.is_available():
        print(f"Bundled USDA DB not available at {usda_local.database_path()}")
        raise SystemExit(1)

    cases = load_cases()
    result = score_search(cases, limit=args.limit)

    print(
        f"food_identity search top-{args.limit} hit rate: "
        f"{result['hits']}/{result['total']} = {result['hit_rate']:.1%}"
    )
    if args.verbose and result["misses"]:
        print("\nMisses:")
        for miss in result["misses"]:
            print(f"  {miss['query']!r} ({miss['category']}):")
            print(f"    top results: {miss.get('top_results', miss.get('error'))}")

    if result["hit_rate"] < 0.90:
        print(
            f"\nBelow SC-004 target of 90% ({result['hit_rate']:.1%}). "
            f"{len(result['misses'])} misses listed above with --verbose."
        )


if __name__ == "__main__":
    main()
