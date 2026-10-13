"""Probe Fastino GLiDE with Mealsy's real judgment requests.

Three modes, all live and all read-only:

    # 1. Does the API accept our routing request? Prints status and answers.
    uv run python eval/probe_glide.py --check

    # 2. Scores for every routing eval case and every memory-judge case, to
    #    set the thresholds in tunables (glide.* and memory.save_min_probability).
    uv run python eval/probe_glide.py --scores

    # 3. Latency of the routing request (go: p50 < 300 ms, p95 < 800 ms at
    #    concurrency 1 from the Railway web container; no-go: p50 > 500 ms).
    uv run python eval/probe_glide.py --n 50 --concurrency 1,5,10
    railway ssh --service web -- python eval/probe_glide.py --n 50

Needs FASTINO_API_KEY. Sends only canned strings and eval-set strings, never
user data. The --scores mode judges routing by GLiDE alone (no Gemini second
opinion), so it runs while the Gemini spend cap is active; eval/gate.py is
still the end-to-end routing gate.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.append(str(Path(__file__).parent.parent / "src"))

from backend.agent import glide  # noqa: E402
from backend.agent.glide import GlideUnavailable  # noqa: E402
from backend.agent.memory_judge import _QUESTIONS as MEMORY_QUESTIONS  # noqa: E402
from backend.agent.system_one import ROUTING_QUESTIONS  # noqa: E402
from backend.config import get_tunables  # noqa: E402

_ROUTING_CASES = Path(__file__).parent / "cases" / "intent_routing.jsonl"
_MEMORY_CASES = Path(__file__).parent / "cases" / "memory_judge.jsonl"
_TIMEOUT_S = 30.0

MESSAGES = (
    "mutton biryani",
    "how much protein have i had today",
    "low fat yogurt",
    "i had pizza, was that bad?",
    "is dosa good for weight loss",
    "2 eggs and toast",
)


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def _check(client: httpx.AsyncClient) -> None:
    """Send one raw routing request and print exactly what comes back."""
    cfg = get_tunables().glide
    start = time.perf_counter()
    response = await client.post(
        "/v1/systemone",
        json={
            "model": cfg.model,
            "state": {"message": MESSAGES[3]},
            "questions": ROUTING_QUESTIONS,
        },
    )
    print(
        f"HTTP {response.status_code} in {(time.perf_counter() - start) * 1000:.0f} ms"
    )
    print(response.text[:3000])


async def _timed(client: httpx.AsyncClient, text: str) -> tuple[float, int]:
    """Send one routing request; return (milliseconds, input tokens)."""
    start = time.perf_counter()
    response = await glide.ask(client, {"message": text}, ROUTING_QUESTIONS)
    return (time.perf_counter() - start) * 1000, response.input_tokens


async def _level(client: httpx.AsyncClient, n: int, concurrency: int) -> None:
    """Run n requests with at most `concurrency` in flight and print the stats."""
    sem = asyncio.Semaphore(concurrency)
    texts = itertools.cycle(MESSAGES)

    async def one(text: str) -> tuple[float, int] | None:
        async with sem:
            try:
                return await _timed(client, text)
            except GlideUnavailable as exc:
                print(f"  failed: {exc.reason}", flush=True)
                return None

    done = [r for r in await asyncio.gather(*(one(next(texts)) for _ in range(n))) if r]
    if not done:
        print(f"concurrency={concurrency}: every request failed")
        return
    ms = sorted(r[0] for r in done)
    p95 = ms[min(len(ms) - 1, int(len(ms) * 0.95))]
    over = sum(1 for m in ms if m > get_tunables().glide.request_timeout_s * 1000)
    print(
        f"concurrency={concurrency:<3} ok={len(done)}/{n:<4} "
        f"p50={ms[len(ms) // 2]:6.0f} ms  p95={p95:6.0f} ms  max={ms[-1]:6.0f} ms  "
        f"over_routing_timeout={over}  "
        f"input_tokens(median)={statistics.median(r[1] for r in done):.0f}",
        flush=True,
    )


async def _routing_scores(client: httpx.AsyncClient, sem: asyncio.Semaphore) -> None:
    """Print GLiDE's own route and certainty for every routing eval case."""
    cfg = get_tunables().glide

    async def one(case: dict) -> tuple[dict, float, float] | None:
        async with sem:
            try:
                response = await glide.ask(
                    client, {"message": case["text"]}, ROUTING_QUESTIONS
                )
                _, probabilities = response.choice("intent")
                return case, probabilities["log_meal"], response.noul("reports_food")
            except (GlideUnavailable, KeyError) as exc:
                print(f"  failed: {exc!r:.60}", flush=True)
                return None

    rows = [r for r in await asyncio.gather(*map(one, _load(_ROUTING_CASES))) if r]
    wrong, unsure, certain_wrong = [], 0, 0
    for case, p_log, _ in rows:
        intent = "log_meal" if p_log >= 0.5 else "coaching"
        certainty = max(p_log, 1 - p_log)
        unsure += certainty < cfg.intent_min_probability
        if intent != case["expect"]:
            wrong.append((certainty, case["text"], case["expect"]))
            certain_wrong += certainty >= cfg.intent_min_probability
    n = len(rows)
    print(f"\n== routing, GLiDE alone: {n - len(wrong)}/{n} correct ==")
    print(
        f"below intent_min_probability={cfg.intent_min_probability} (would go to "
        f"Gemini): {unsure}/{n}; wrong AND acted on directly: {certain_wrong}"
    )
    for certainty, text, expect in sorted(wrong, reverse=True):
        print(f"  WRONG certainty={certainty:.2f} expect={expect:<9} {text!r}")
    certainties = sorted(max(p, 1 - p) for _, p, _ in rows)
    print(
        "certainty deciles:",
        " ".join(f"{q:.2f}" for q in certainties[:: max(1, n // 10)]),
    )

    offers = [(c, rf) for c, _, rf in rows if "expect_offer" in c]
    if offers:
        print(f"\n== reports_food (threshold {cfg.log_offer_min_probability}) ==")
        for case, reports_food in sorted(offers, key=lambda o: o[1]):
            got = reports_food >= cfg.log_offer_min_probability
            flag = "ok   " if got == case["expect_offer"] else "WRONG"
            print(
                f"  {flag} p={reports_food:.2f} "
                f"expect={case['expect_offer']!s:<5} {case['text']!r}"
            )


async def _memory_scores(client: httpx.AsyncClient, sem: asyncio.Semaphore) -> None:
    """Print the save-decision probability for every memory-judge case."""
    threshold = get_tunables().memory.save_min_probability

    async def one(case: dict) -> tuple[dict, float] | None:
        question = case["question"]
        async with sem:
            try:
                response = await glide.ask(
                    client,
                    {"message": case["message"], "candidate": case["candidate"]},
                    {question: MEMORY_QUESTIONS[question]},
                )
                return case, response.noul(question)
            except GlideUnavailable as exc:
                print(f"  failed: {exc.reason}", flush=True)
                return None

    rows = [r for r in await asyncio.gather(*map(one, _load(_MEMORY_CASES))) if r]
    right = sum((p >= threshold) == case["expect"] for case, p in rows)
    print(f"\n== memory judge at threshold {threshold}: {right}/{len(rows)} correct ==")
    for case, p in sorted(rows, key=lambda r: (r[0]["expect"], r[1])):
        flag = "ok   " if (p >= threshold) == case["expect"] else "WRONG"
        print(
            f"  {flag} p={p:.2f} keep={case['expect']!s:<5} "
            f"{case['message']!r} -> {case['candidate']!r}"
        )
    keep = [p for case, p in rows if case["expect"]]
    drop = [p for case, p in rows if not case["expect"]]
    if keep and drop:
        print(f"lowest keep={min(keep):.2f}  highest drop={max(drop):.2f}")


async def main() -> None:
    """Parse arguments and run the chosen probe."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="one raw request")
    ap.add_argument("--scores", action="store_true", help="score the eval cases")
    ap.add_argument("--n", type=int, default=50, help="requests per level")
    ap.add_argument("--concurrency", default="1,5,10", help="comma-separated levels")
    args = ap.parse_args()

    # Generous timeout: we are measuring, not routing.
    client = glide.make_client(_TIMEOUT_S)
    if client is None:
        raise SystemExit(f"{glide.API_KEY_ENV} is not set")
    async with client:
        if args.check:
            await _check(client)
            return
        if args.scores:
            sem = asyncio.Semaphore(4)
            await _routing_scores(client, sem)
            await _memory_scores(client, sem)
            return
        try:
            await _timed(client, "warm up")
        except GlideUnavailable as exc:
            raise SystemExit(f"warm-up failed: {exc.reason}") from None
        for level in (int(x) for x in args.concurrency.split(",") if x.strip()):
            await _level(client, args.n, level)


if __name__ == "__main__":
    asyncio.run(main())
