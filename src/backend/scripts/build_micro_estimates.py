"""Pre-compute AI estimates for tracked nutrients USDA lacks (spec 008 R6).

For every food in the bundled USDA SQLite, asks Gemini Flash-Lite for the
estimable catalogue nutrients that food's USDA record does not report, given
its description and the nutrients USDA *does* report. Accepted values (within
``max_per_100g``; added sugars never above total sugars) are written to the
``food_micro_estimate`` table, so a USDA-matched item never needs an AI call
at log time.

The full run costs real money (~13.7k calls). Always run ``--dry-run`` first
and get approval before the full build.

Usage:
    PYTHONPATH=src python -m backend.scripts.build_micro_estimates --dry-run
    PYTHONPATH=src python -m backend.scripts.build_micro_estimates --limit 50
    PYTHONPATH=src python -m backend.scripts.build_micro_estimates --benchmark 50
    PYTHONPATH=src python -m backend.scripts.build_micro_estimates  # full run

Re-runnable: foods/keys already estimated are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sqlite3
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, create_model
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings

from backend.agent.llm import FLASH_LITE_MODEL
from backend.agent.tools import usda_local
from backend.config import get_tunables
from backend.nutrients import catalog
from backend.nutrients.resolve import per_100g_from_usda
from backend.scripts.build_usda_db import MICRO_ESTIMATE_DDL

logger = logging.getLogger(__name__)

# Rough Flash-Lite list prices (USD per 1M tokens) for the dry-run estimate.
_PRICE_IN = 0.10
_PRICE_OUT = 0.40
_BASE_PROMPT_TOKENS = 350
_TOKENS_PER_KNOWN = 12
_TOKENS_PER_REQUEST_KEY = 15
_TOKENS_PER_OUTPUT_KEY = 10
_BENCH_TOLERANCE = 0.5  # ±50% (SC-004)
_BENCH_TARGET = 0.70

_SYSTEM = """You estimate nutrient content of foods from food-composition
knowledge. You are given a USDA food description and the nutrients USDA
already reports for it (per 100 g). Estimate ONLY the requested nutrients,
PER 100 g of the food as described, in the unit stated for each field.
Added sugars are sugars added in processing or preparation and can never
exceed total sugars. Return null for any nutrient you cannot estimate with
reasonable confidence; never guess wildly."""


def _gap_model() -> type[BaseModel]:
    """Structured output: one optional per-100 g field per estimable key."""
    fields = {
        key: (
            float | None,
            Field(
                default=None,
                ge=0.0,
                description=f"{catalog.nutrient(key).name}, "
                f"{catalog.nutrient(key).unit} per 100 g",
            ),
        )
        for key in catalog.estimable_keys()
    }
    return create_model("GapEstimate", __config__=ConfigDict(extra="forbid"), **fields)


GapEstimate = _gap_model()

_agent = Agent(
    GoogleModel(FLASH_LITE_MODEL),
    output_type=GapEstimate,
    system_prompt=_SYSTEM,
    model_settings=GoogleModelSettings(
        google_thinking_config={
            "thinking_budget": get_tunables().token_limits.extraction_thinking_budget
        }
    ),
)


@dataclass
class FoodGap:
    """One food and the estimable keys it still lacks."""

    fdc_id: int
    description: str
    known: dict[str, float]  # key -> per-100 g USDA value
    missing: list[str]


def _connect(path: Path, write: bool) -> sqlite3.Connection:
    """Open the bundled DB; in write mode ensure the v3 estimate table exists."""
    if not write:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn = sqlite3.connect(path)
    conn.executescript(MICRO_ESTIMATE_DDL)
    conn.execute("PRAGMA user_version = 3")
    return conn


def _gaps(conn: sqlite3.Connection) -> list[FoodGap]:
    """Every food with at least one estimable key not yet covered."""
    done: dict[int, set[str]] = {}
    try:
        rows = conn.execute("SELECT fdc_id, key FROM food_micro_estimate").fetchall()
    except sqlite3.OperationalError:  # pre-v3 DB opened read-only (dry run)
        rows = []
    for fdc_id, key in rows:
        done.setdefault(fdc_id, set()).add(key)
    estimable = catalog.estimable_keys()
    gaps: list[FoodGap] = []
    rows = conn.execute("SELECT fdc_id, description, nutrients_z FROM food")
    for fdc_id, description, blob in rows:
        mapped = per_100g_from_usda(json.loads(zlib.decompress(blob)), estimates={})
        known = {k: v for k, (v, _) in mapped.items()}
        missing = [
            k for k in estimable if k not in known and k not in done.get(fdc_id, set())
        ]
        if missing:
            gaps.append(FoodGap(fdc_id, description, known, missing))
    return gaps


def _prompt(description: str, known: dict[str, float], keys: list[str]) -> str:
    """User prompt: description, USDA-known values, requested keys."""
    known_lines = "\n".join(
        f"- {catalog.nutrient(k).name}: {v:g} {catalog.nutrient(k).unit}"
        for k, v in known.items()
    )
    wanted = ", ".join(keys)
    return (
        f"Food: {description}\n\nUSDA reports per 100 g:\n{known_lines or '- none'}"
        f"\n\nEstimate per 100 g ONLY these fields (others null): {wanted}"
    )


def _accept(
    key: str, value: float | None, known: dict[str, float], got: dict[str, float]
) -> bool:
    """Apply the catalogue cap and the added ≤ total sugars rule."""
    if value is None or value < 0:
        return False
    cap = catalog.nutrient(key).max_per_100g
    if cap is not None and value > cap:
        return False
    if key == "added_sugars":
        total = known.get("total_sugars", got.get("total_sugars"))
        if total is not None and value > total:
            return False
    return True


async def _estimate(
    gap: FoodGap, keys: list[str], known: dict[str, float], sem: asyncio.Semaphore
) -> dict[str, float]:
    """One model call for one food; returns accepted key -> value."""
    async with sem:
        try:
            run = await _agent.run(_prompt(gap.description, known, keys))
        except Exception as exc:  # noqa: BLE001 — any provider failure: skip food
            logger.warning("estimate failed for %s: %s", gap.fdc_id, exc)
            return {}
    raw = run.output.model_dump()
    got = {k: raw.get(k) for k in keys if raw.get(k) is not None}
    return {k: v for k, v in got.items() if _accept(k, v, known, got)}


def dry_run(gaps: list[FoodGap]) -> None:
    """Print counts and a token/cost estimate; makes no calls."""
    n_keys = sum(len(g.missing) for g in gaps)
    tokens_in = sum(
        _BASE_PROMPT_TOKENS
        + _TOKENS_PER_KNOWN * len(g.known)
        + _TOKENS_PER_REQUEST_KEY * len(g.missing)
        for g in gaps
    )
    tokens_out = _TOKENS_PER_OUTPUT_KEY * n_keys
    cost = tokens_in / 1e6 * _PRICE_IN + tokens_out / 1e6 * _PRICE_OUT
    per_key = Counter(k for g in gaps for k in g.missing)
    print(f"foods needing estimates: {len(gaps)}")
    print(f"missing (food, key) pairs: {n_keys}")
    print(f"est. tokens: {tokens_in:,} in + {tokens_out:,} out ≈ ${cost:.2f}")
    print(
        "most-missing keys:", ", ".join(f"{k}={n}" for k, n in per_key.most_common(8))
    )


async def build(
    conn: sqlite3.Connection, gaps: list[FoodGap], concurrency: int
) -> None:
    """Estimate every gap and insert accepted values (committed per food)."""
    sem = asyncio.Semaphore(concurrency)
    rejected = Counter()
    accepted = 0

    async def one(gap: FoodGap) -> None:
        nonlocal accepted
        values = await _estimate(gap, gap.missing, gap.known, sem)
        rejected.update(k for k in gap.missing if k not in values)
        conn.executemany(
            "INSERT OR REPLACE INTO food_micro_estimate (fdc_id, key, per_100g) "
            "VALUES (?, ?, ?)",
            [(gap.fdc_id, k, v) for k, v in values.items()],
        )
        conn.commit()
        accepted += len(values)

    await asyncio.gather(*[one(g) for g in gaps])
    total = sum(len(g.missing) for g in gaps) or 1
    print(f"accepted {accepted} values; rejected/null {total - accepted}")
    for key, n in rejected.most_common():
        print(f"  {key:22} not filled for {n} foods")


async def benchmark(conn: sqlite3.Connection, n: int, concurrency: int) -> float:
    """SC-004: hide USDA values for N foods, estimate them, report ±50% share."""
    rng = random.Random(8)
    estimable = set(catalog.estimable_keys())
    pool: list[FoodGap] = []
    for fdc_id, description, blob in conn.execute(
        "SELECT fdc_id, description, nutrients_z FROM food"
    ):
        mapped = per_100g_from_usda(json.loads(zlib.decompress(blob)), estimates={})
        known = {k: v for k, (v, _) in mapped.items() if k in estimable}
        if len(known) >= 20:
            pool.append(FoodGap(fdc_id, description, known, []))
    sample = rng.sample(pool, min(n, len(pool)))
    sem = asyncio.Semaphore(concurrency)
    hidden_keys = [
        "vitamin_c",
        "iron",
        "calcium",
        "potassium",
        "magnesium",
        "zinc",
        "vitamin_b6",
        "folate",
        "sodium",
        "cholesterol",
    ]

    async def one(food: FoodGap) -> list[bool]:
        keys = [k for k in hidden_keys if k in food.known]
        context = {
            k: v
            for k, v in food.known.items()
            if k in {"water", "total_sugars", "saturated_fat"}
        }
        got = await _estimate(food, keys, context, sem)
        out = []
        for k in keys:
            truth, est = food.known[k], got.get(k)
            if est is None:
                out.append(False)
            elif truth == 0:
                out.append(est <= 0.01 * (catalog.nutrient(k).max_per_100g or 1))
            else:
                out.append(abs(est - truth) <= _BENCH_TOLERANCE * truth)
        return out

    results = [ok for food in await asyncio.gather(*map(one, sample)) for ok in food]
    share = sum(results) / len(results) if results else 0.0
    verdict = "PASS" if share >= _BENCH_TARGET else "FAIL"
    print(f"benchmark: {sum(results)}/{len(results)} within ±50% = {share:.0%}")
    print(f"SC-004 (≥{_BENCH_TARGET:.0%}): {verdict}")
    return share


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count + cost only")
    parser.add_argument("--limit", type=int, default=None, help="first N foods")
    parser.add_argument("--benchmark", type=int, default=None, metavar="N")
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    write = not (args.dry_run or args.benchmark)
    conn = _connect(usda_local.database_path(), write=write)
    if args.benchmark:
        asyncio.run(benchmark(conn, args.benchmark, args.concurrency))
        return
    gaps = _gaps(conn)
    if args.limit is not None:
        gaps = gaps[: args.limit]
    dry_run(gaps)
    if not args.dry_run:
        asyncio.run(build(conn, gaps, args.concurrency))


if __name__ == "__main__":
    main()
