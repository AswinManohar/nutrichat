"""Measure TypeSafe Jev latency for the routing request (spec SC-003, FR-013).

Sends the exact three-question routing request the orchestrator sends, at
several concurrency levels, and prints p50 / p95 / max wall-clock per request.
Run it from the dev machine and from inside the Railway ``web`` container; the
container number is the go / no-go gate (p50 < 300 ms, p95 < 800 ms at
concurrency 1; no-go if p50 > 500 ms).

    uv run python eval/probe_jev_latency.py --n 50 --concurrency 1,5,10
    railway ssh --service web -- python eval/probe_jev_latency.py --n 50

Needs TYPESAFE_API_KEY. Sends only canned food/question strings, never user data.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import os
import statistics
import sys
import time
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

sys.path.append(str(Path(__file__).parent.parent / "src"))

from backend.agent.system_one import ROUTING_QUESTIONS  # noqa: E402

MESSAGES = (
    "mutton biryani",
    "how much protein have i had today",
    "low fat yogurt",
    "i had pizza, was that bad?",
    "is dosa good for weight loss",
    "2 eggs and toast",
)


async def _timed(client: AsyncTypeSafeClient, text: str) -> tuple[float, int]:
    """Send one routing request; return (milliseconds, input tokens)."""
    start = time.perf_counter()
    response = await client.system_one({"message": text}, ROUTING_QUESTIONS)
    return (time.perf_counter() - start) * 1000, response.usage.input_tokens


async def _level(client: AsyncTypeSafeClient, n: int, concurrency: int) -> None:
    """Run n requests with at most `concurrency` in flight and print the stats."""
    sem = asyncio.Semaphore(concurrency)
    texts = itertools.cycle(MESSAGES)

    async def one(text: str) -> tuple[float, int]:
        async with sem:
            return await _timed(client, text)

    results = await asyncio.gather(*(one(next(texts)) for _ in range(n)))
    ms = sorted(r[0] for r in results)
    p95 = ms[min(len(ms) - 1, int(len(ms) * 0.95))]
    print(
        f"concurrency={concurrency:<3} n={n:<4} p50={ms[len(ms) // 2]:6.0f} ms  "
        f"p95={p95:6.0f} ms  max={ms[-1]:6.0f} ms  "
        f"input_tokens(median)={statistics.median(r[1] for r in results):.0f}",
        flush=True,
    )


async def main() -> None:
    """Parse arguments, warm the connection, and probe each concurrency level."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=50, help="requests per level")
    ap.add_argument("--concurrency", default="1,5,10", help="comma-separated levels")
    args = ap.parse_args()
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY is not set")
    levels = [int(x) for x in args.concurrency.split(",") if x.strip()]

    # Generous timeout and no retries: we are measuring, not routing.
    async with AsyncTypeSafeClient(
        timeout=10.0, retry=RetryPolicy(max_retries=0)
    ) as client:
        await _timed(client, "warm up")
        for level in levels:
            await _level(client, args.n, level)


if __name__ == "__main__":
    asyncio.run(main())
