"""Quality gate for latency changes to the meal-logging pipeline.

Scores five categories against the rule decided in
`.scratch/logging-latency/issues/03-the-quality-gate.md`:

    A latency change is accepted only if, across at least 5 runs per case, its mean
    score in EVERY category stays within that category's tolerance of the baseline
    mean -- where each tolerance is strictly greater than the measured noise band.

Because the pipeline is non-deterministic, every category is run N times and reported
as mean +/- noise band. Run with no baseline to establish one; run with --baseline to
score a change against it.

    uv run --env-file .env python eval/gate.py --runs 5
    uv run --env-file .env python eval/gate.py --runs 5 \
        --baseline eval/baseline_scores.json

Decomposition is scored on resulting MACRO TOTALS, not ingredient-list similarity: a
dish split five ways or nine ways is the same answer if the kcal and macros land in the
same place.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).parent.parent / "src"))
load_dotenv(Path(__file__).parent.parent / ".env")

CASES_DIR = Path(__file__).parent / "cases"

# Synthetic user for intent routing, which consumes an LLM quota credit per call.
TEST_USER = "00000000-0000-0000-0000-0000000000bb"

# Max concurrent LLM calls. Gemini rate limits are the binding constraint.
CONCURRENCY = 5

QTY_TOL = 0.25  # counted grams must land within +/-25% of count x singular

# Per-category tolerances. TWO constraints bind, and the original values
# satisfied only the first:
#
#   1. tolerance > 95% CI of the mean over N runs (the noise constraint), and
#   2. tolerance >= granularity = 100/len(cases) (the RESOLUTION constraint).
#
# (2) was missed originally and made every percentage category unusable: with
# 8 quantity cases one case flipping moves the score 12.5pp, against a 5.0pp
# tolerance -- so any real change failed, and only a byte-identical score could
# pass. A tolerance finer than a single case cannot be satisfied by anything the
# metric is capable of measuring. _validate_tolerances() below enforces (2) at
# run time so this cannot silently return.
#
# Consequence worth stating plainly: with case sets this small the gate is
# COARSE. It detects "a case or two broke", not fine drift. The way to tighten
# it is more cases, never a smaller tolerance.
TOLERANCES: dict[str, float] = {
    "entity_recall": 10.0,  # 12 cases -> 8.3pp granularity; CI 0.0pp
    "quantity": 8.0,  # 24 cases -> 4.2pp granularity; CI 6.6pp (extraction is noisy)
    "food_identity": 8.0,  # 14 cases -> 7.1pp granularity; CI 5.2pp
    "intent_routing": 8.0,  # 14 cases -> 7.1pp granularity; CI 0.0pp
    # Not a percentage of cases, so granularity does not apply -- but the
    # measured CI of the mean at N=5 is ~16% (haleem alone swings 45%
    # run-to-run), so anything under that is noise. Raise N to tighten.
    "decomposition_kcal_pct": 25.0,
}


def load_cases(name: str) -> list[dict]:
    """Read one JSONL case file."""
    path = CASES_DIR / f"{name}.jsonl"
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _granularity(category: str) -> float:
    """Smallest score change a single case can produce, in percentage points.

    Args:
        category: Case-set name, e.g. "quantity".

    Returns:
        100 / number_of_cases.
    """
    return 100.0 / len(load_cases(category))


def _validate_tolerances() -> None:
    """Fail loudly if any tolerance is finer than one case's worth of score.

    A tolerance below the granularity can never be satisfied by a real change:
    the smallest movement the metric can express already exceeds it. Catching
    this at startup stops the gate from reporting confident FAILs it has no
    resolution to justify.

    Raises:
        SystemExit: If any percentage category is mis-specified.
    """
    problems = []
    for category, tol in TOLERANCES.items():
        if category == "decomposition_kcal_pct":
            continue
        gran = _granularity(category)
        if tol < gran:
            problems.append(
                f"  {category}: tolerance {tol}pp < granularity {gran:.1f}pp "
                f"({len(load_cases(category))} cases) -- add cases or raise it"
            )
    if problems:
        raise SystemExit("Mis-specified gate tolerances:\n" + "\n".join(problems))


def _matches(text: str, alternatives: list[str]) -> bool:
    """True if any alternative appears as a substring of text (case-insensitive)."""
    low = text.lower()
    return any(alt.lower() in low for alt in alternatives)


# ---------------------------------------------------------------------------
# Category scorers. Each returns a float score for one run.
# ---------------------------------------------------------------------------


async def score_entity_recall(sem: asyncio.Semaphore) -> float:
    """F1 over foods named in a sentence: recall of expected, precision against extras.

    Calls extract_entities directly (pre-decomposition) because this measures
    extraction, not what the graph later does with the result.
    """
    from backend.agent.tools.meals import extract_entities

    cases = load_cases("entity_recall")

    async def one(case: dict) -> tuple[float, float]:
        async with sem:
            result = await asyncio.to_thread(extract_entities, case["text"])
        names = [e.food_name for e in result.entities if e.qty_g > 0]
        expected: list[list[str]] = case["expect"]
        hit = sum(1 for grp in expected if any(_matches(n, grp) for n in names))
        used = sum(1 for n in names if any(_matches(n, grp) for grp in expected))
        recall = hit / len(expected) if expected else 0.0
        precision = used / len(names) if names else 0.0
        return recall, precision

    pairs = await asyncio.gather(*(one(c) for c in cases))
    r = statistics.fmean(p[0] for p in pairs)
    p = statistics.fmean(p[1] for p in pairs)
    return 0.0 if (r + p) == 0 else 100 * 2 * r * p / (r + p)


async def score_quantity(sem: asyncio.Semaphore) -> float:
    """Percent of foods whose counted grams scale linearly from the singular phrase."""
    from backend.agent.tools.meals import extract_entities

    cases = load_cases("quantity")

    async def first_qty(phrase: str) -> float | None:
        async with sem:
            result = await asyncio.to_thread(extract_entities, phrase)
        valid = [e for e in result.entities if e.qty_g > 0]
        return valid[0].qty_g if valid else None

    async def one(case: dict) -> float:
        one_g, many_g = await asyncio.gather(
            first_qty(case["singular"]), first_qty(case["counted"])
        )
        if not one_g or not many_g:
            return 0.0
        ratio = many_g / one_g
        return 1.0 if abs(ratio - case["n"]) <= case["n"] * QTY_TOL else 0.0

    return 100 * statistics.fmean(await asyncio.gather(*(one(c) for c in cases)))


async def score_food_identity(sem: asyncio.Semaphore) -> float:
    """Recall@1 of the USDA match for a food name."""
    from backend.agent.tools.usda import _EntityShim, usda_lookup_batch

    cases = load_cases("food_identity")
    async with sem:
        results = await usda_lookup_batch(
            [_EntityShim(food_name=c["query"], qty_g=100.0) for c in cases]
        )
    hits = 0
    for case, result in zip(cases, results):
        # An LLM estimate is never a food-identity hit. estimate_nutrition_llm
        # echoes the query back as food_name, so without this guard a fallback
        # scores against itself for every case whose acceptable_name_substrings
        # contain the query (6 of the 14 today) — hiding the exact regression
        # this category exists to detect.
        if result.estimated or result.source != "USDA":
            continue
        if result.fdc_id in case.get("acceptable_fdc_ids", []):
            hits += 1
        elif result.food_name and _matches(
            result.food_name, case.get("acceptable_name_substrings", [])
        ):
            hits += 1
    return 100 * hits / len(cases)


async def score_intent_routing(sem: asyncio.Semaphore) -> float:
    """Accuracy of log_meal vs coaching routing."""
    from backend.agent.orchestrator import _classify_intent

    cases = load_cases("intent_routing")

    async def one(case: dict) -> float:
        async with sem:
            got = await _classify_intent(case["text"], TEST_USER)
        return 1.0 if got == case["expect"] else 0.0

    return 100 * statistics.fmean(await asyncio.gather(*(one(c) for c in cases)))


async def score_decomposition(sem: asyncio.Semaphore) -> dict[str, float]:
    """Total kcal per dish after decomposition + USDA resolution.

    Not a percentage: this category is judged on whether the macros a user ends up
    with stay put, so the raw totals are the score and the tolerance is a percentage
    delta against them.
    """
    from backend.agent.tools.decompose import decompose_to_entities
    from backend.agent.tools.usda import usda_lookup_batch

    cases = load_cases("decomposition")

    async def one(case: dict) -> tuple[str, float]:
        desc = f"{case['qty_g']:g} g {case['dish']}"
        async with sem:
            parts = await asyncio.to_thread(decompose_to_entities, desc)
        parts = [e for e in parts if e.qty_g > 0]
        if not parts:
            return case["dish"], 0.0
        async with sem:
            resolved = await usda_lookup_batch(parts)
        return case["dish"], sum(r.kcal for r in resolved)

    return dict(await asyncio.gather(*(one(c) for c in cases)))


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


async def prepare_user() -> None:
    """Give the intent-routing test user effectively unlimited quota."""
    from sqlalchemy import text

    from backend.db.session import get_session

    async with get_session()() as s:
        await s.execute(
            text(
                "INSERT INTO user_goal (user_id, llm_requests_used, llm_quota) "
                "VALUES (:u, 0, 1000000) ON CONFLICT (user_id) DO UPDATE "
                "SET llm_requests_used = 0, llm_quota = 1000000"
            ),
            {"u": TEST_USER},
        )
        await s.commit()


async def cleanup_user() -> None:
    """Remove the synthetic quota row."""
    from sqlalchemy import text

    from backend.db.session import get_session

    async with get_session()() as s:
        await s.execute(
            text("DELETE FROM user_goal WHERE user_id = :u"), {"u": TEST_USER}
        )
        await s.commit()


def band(values: list[float]) -> dict[str, float]:
    """Mean, spread, and noise band (max - min) for repeated runs of one category."""
    return {
        "mean": round(statistics.fmean(values), 2),
        "stdev": round(statistics.stdev(values), 2) if len(values) > 1 else 0.0,
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "noise_band": round(max(values) - min(values), 2),
        "runs": values,
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=5, help="repeats per category (N>=5)")
    ap.add_argument("--baseline", type=Path, help="score against this baseline JSON")
    ap.add_argument(
        "--out",
        type=Path,
        help="write the report here (default: the baseline file when establishing a "
        "baseline; nothing when scoring against one)",
    )
    args = ap.parse_args()
    _validate_tolerances()

    default_baseline = Path(__file__).parent / "baseline_scores.json"
    # Establishing a baseline writes it; scoring a change against one must NOT, or the
    # report overwrites its own reference and every delta comes out as exactly +0.0.
    out_path = args.out if args.out else (None if args.baseline else default_baseline)

    # Read the reference up front, so no later write can shadow it.
    base: dict[str, Any] | None = None
    if args.baseline:
        if not args.baseline.exists():
            ap.error(f"baseline not found: {args.baseline}")
        with open(args.baseline) as f:
            base = json.load(f)
        if out_path and out_path.resolve() == args.baseline.resolve():
            ap.error("--out would overwrite the baseline being scored against")

    sem = asyncio.Semaphore(CONCURRENCY)
    await prepare_user()

    pct_scores: dict[str, list[float]] = {
        "entity_recall": [],
        "quantity": [],
        "food_identity": [],
        "intent_routing": [],
    }
    decomp_runs: list[dict[str, float]] = []

    try:
        for i in range(args.runs):
            print(f"run {i + 1}/{args.runs} ...", flush=True)
            e, q, f, r, dec = await asyncio.gather(
                score_entity_recall(sem),
                score_quantity(sem),
                score_food_identity(sem),
                score_intent_routing(sem),
                score_decomposition(sem),
            )
            pct_scores["entity_recall"].append(e)
            pct_scores["quantity"].append(q)
            pct_scores["food_identity"].append(f)
            pct_scores["intent_routing"].append(r)
            decomp_runs.append(dec)
            print(
                f"  entity_recall={e:.1f}  quantity={q:.1f}  "
                f"food_identity={f:.1f}  intent_routing={r:.1f}",
                flush=True,
            )
    finally:
        await cleanup_user()

    report: dict[str, Any] = {k: band(v) for k, v in pct_scores.items()}

    dishes = sorted(decomp_runs[0]) if decomp_runs else []
    per_dish = {d: band([run[d] for run in decomp_runs]) for d in dishes}
    # Category-level noise for decomposition is the worst dish's spread as a percentage
    # of its own mean -- a dish whose kcal swings 30% between identical runs sets the
    # floor for any tolerance we could apply to the category.
    worst = max(
        (
            (d, 100 * per_dish[d]["noise_band"] / per_dish[d]["mean"])
            for d in dishes
            if per_dish[d]["mean"] > 0
        ),
        key=lambda t: t[1],
        default=("-", 0.0),
    )
    report["decomposition_kcal"] = {
        "per_dish": per_dish,
        "worst_dish": worst[0],
        "worst_noise_pct": round(worst[1], 2),
    }

    if out_path:
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)

    print("\n=== noise band (identical code, repeated runs) ===")
    for cat in pct_scores:
        b = report[cat]
        print(
            f"{cat:16} mean={b['mean']:6.1f}  band={b['noise_band']:5.1f}pp  "
            f"(min {b['min']:.1f} / max {b['max']:.1f})"
        )
    print(
        f"\n{'decomposition kcal':16} worst dish: {worst[0]} "
        f"swings {worst[1]:.1f}% across identical runs"
    )
    for d in dishes:
        b = per_dish[d]
        pctb = 100 * b["noise_band"] / b["mean"] if b["mean"] else 0
        print(f"  {d:20} mean={b['mean']:8.0f} kcal  band={pctb:5.1f}%")

    if base is not None:
        failures: list[str] = []
        print("\n=== delta vs baseline ===")
        for cat in pct_scores:
            delta = report[cat]["mean"] - base[cat]["mean"]
            tol = TOLERANCES[cat]
            verdict = "PASS" if delta >= -tol else "FAIL"
            if verdict == "FAIL":
                failures.append(cat)
            print(f"{cat:16} {delta:+6.1f}pp  (tolerance {tol:.1f}pp)  {verdict}")
        base_dish = base["decomposition_kcal"]["per_dish"]
        tol_pct = TOLERANCES["decomposition_kcal_pct"]
        for dish, b in per_dish.items():
            if dish not in base_dish or not base_dish[dish]["mean"]:
                continue
            delta = (
                100 * (b["mean"] - base_dish[dish]["mean"]) / base_dish[dish]["mean"]
            )
            verdict = "PASS" if abs(delta) <= tol_pct else "FAIL"
            if verdict == "FAIL":
                failures.append(f"decomp:{dish}")
            print(
                f"decomp:{dish:<16} {delta:+6.1f}%  "
                f"(tolerance +/-{tol_pct:.0f}%)  {verdict}"
            )
        print(f"\nGATE: {'FAIL -- ' + ', '.join(failures) if failures else 'PASS'}")
    if out_path:
        print(f"\nwrote {out_path}")
    if base is not None and failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
