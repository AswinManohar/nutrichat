# Quickstart: validating calibrated intent routing

**Spec**: [spec.md](spec.md) · **Contracts**: [contracts/](contracts/) ·
**Data model**: [data-model.md](data-model.md)

Validation scenarios, in the order they gate the feature. Commands assume the
repo root and the project venv (`uv sync`).

## Prerequisites

- `TYPESAFE_API_KEY` from console.typesafe.ai, exported in the shell or in
  `.env` (never committed). Rotate the key that was pasted into chat before
  using it anywhere shared.
- `GOOGLE_API_KEY` for the Gemini second opinion.
- Local Postgres + Redis only for scenarios 4–6 (`scripts/run-local --local-db`).

## 1. Unit tests: no network, both paths (FR-004–FR-009, FR-015)

```bash
PYTHONPATH=src pytest tests/test_system_one.py tests/test_orchestrator.py \
  tests/test_orchestrator_quota.py tests/test_coaching*.py -q
```

Expect green with `TYPESAFE_API_KEY` exported too: `tests/conftest.py`
removes it, so nothing reaches TypeSafe. Tests must cover: confident route
acted on with no Gemini call; unsure route → Gemini; every failure class →
Gemini; paused/photo turns never await the judgment; no path calls
`consume_llm_credit`; offer appended only when `reports_food` clears its bar;
request state contains only `message`; eval texts never appear in question
examples.

## 2. Baseline of today's router (FR-012). Run before any deletion

```bash
PYTHONPATH=src python eval/gate.py --only intent_routing --runs 5 \
  --out eval/baseline_intent_legacy.json
```

Expect per-category accuracy for the keyword+Gemini router on the ≥ 60-case
set, committed. The `bare_food_nutrient_word` category should show the known
failure.

## 3. Router quality gate (SC-001, SC-002, SC-011)

```bash
PYTHONPATH=src python eval/gate.py --only intent_routing --runs 5 \
  --baseline eval/baseline_intent_legacy.json
```

(`--runs`, `--baseline` and `--out` exist today; `--only` is added by this
feature so the intent category can run without the USDA/extraction categories.)

Expect: overall ≥ 95%, `bare_food_nutrient_word` ≥ 95%, no category worse than
the legacy baseline beyond its 95% CI, offer shown on ≥ 90% of `mixed` and
≤ 5% of `expect_offer: false` cases. **Also check the printed path split**: if
many cases were decided by `second_opinion_unavailable`, the score is Gemini's,
not Jev's. Re-run at lower concurrency (research R5).

## 4. Latency gate from production (FR-013, SC-003)

```bash
railway ssh --service web -- \
  python eval/probe_jev_latency.py --n 50 --concurrency 1,5,10
```

Expect at concurrency 1: p50 < 300 ms, p95 < 800 ms. **No-go** if p50 > 500 ms.
Record the concurrency 5/10 numbers. If p95 there exceeds the 0.8 s timeout,
raise `request_timeout_s` or cap in-flight requests before enabling (research
R5). Dev-machine reference, 2026-09-21: sequential p50 274 / p95 346 ms;
10 concurrent p50 799 ms.

## 5. Outage drill (Story 3, SC-006)

Run the app locally three ways and send "protein shake", "is rice healthy?",
"I had pizza, was that bad?":

| Setup | Expected |
|---|---|
| `TYPESAFE_API_KEY` unset | one startup warning; all three routed correctly via Gemini; no offer appended; no credit spent on routing |
| `TYPESAFE_BASE_URL=http://10.255.255.1` (black hole) | same replies; each turn ≤ 0.8 s + Gemini slower; `route_message.failure = TypeSafeAPITimeoutError` |
| Invalid key | same replies; `failure = TypeSafeAuthenticationError` |

## 6. End-to-end on web and Telegram (Story 1, Story 5, FR-016)

With a valid key, on both the web chat and the Telegram bot:

1. "protein shake" → meal card.
2. "how much protein have I had today?" → coaching reply with totals.
3. "hi" → conversational coaching reply, no card.
4. "I had pizza, was that bad?" → coaching reply ending in the offer. Then
   "two slices of pizza" → meal card.
5. With a card pending, send "yes" → meal logged exactly as before.
6. Query the last coaching rows:

   ```sql
   select query, parsed_query->'needs_guidance' as gemini,
          parsed_query->'routing' as routing
   from coaching_response order by created_at desc limit 5;
   ```

   Expect `routing.needs_guidance_jev` and `routing.path` on every row that
   Jev routed; guideline citations unchanged from before.

## 7. After launch (SC-004, SC-005, SC-009, SC-010)

- Re-run the per-node latency baseline from `.scratch/logging-latency`
  (container method) and compare cue-less vs cue-bearing meal messages.
- SC-010 agreement, once ≥ 200 coaching rows carry `routing`: share of rows
  where `(needs_guidance_jev >= 0.5) == needs_guidance`. That number decides
  whether the separate early-fetch feature is worth specifying.
