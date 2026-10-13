# Research: Jev → GLiDE

**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)

Sources: `https://docs.fastino.ai/inference/systemone` (incl. "Migrating from
TypeSafe"), `https://docs.fastino.ai/openapi.json`, the installed
`fastino-glide` skill, and the current code (`src/backend/agent/system_one.py`,
`orchestrator.py`, `eval/gate.py`, `eval/probe_jev_latency.py`).

## Measured 2026-10-13 (dev machine, `eval/probe_glide.py`)

| Check | Result |
|---|---|
| Request accepted as written | Yes. HTTP 200 with the nested `intent` criteria; model `fastino/GLiDE`; response `model` is `glide_v2` |
| Input tokens per routing request | 621 (median), about $0.09 per 1,000 messages |
| Routing, GLiDE alone, 94 cases | 94/94 correct; 2 below the 0.75 bar (lowest 0.67), so 98% decided without Gemini |
| `reports_food` | all 41 labelled cases right at 0.7; yes >= 0.99, no <= 0.02 |
| Memory judge, 32 cases | 32/32 at 0.6; keep >= 0.84, drop <= 0.09 |
| Latency, concurrency 1 / 5 / 10 (50 each) | p50 360 / 405 / 389 ms; p95 615 / 584 / 610 ms; max 691 ms; 0 of 150 over 0.8 s |

Jev from the same machine was p95 346 ms sequential and about 800 ms at 10
concurrent: GLiDE is slower for a single request and steadier under load. p50
is above the 300 ms go bar and below the 500 ms no-go, so the container
measurement decides.

**End-to-end routing gate** (`eval/gate.py`, 5 runs, 94 cases, 2026-10-13):
100.0% in every run against the legacy baseline's 77.3% (PASS). Decided by
the judgment alone 97.7%, second opinion because unsure 2.1%, because GLiDE
timed out 0.2% (1 of 470 requests); offer to log 100% recall, no false offers.
The same result was measured twice: once with `gemini-3.8-flash` as the
second opinion and once with `gemini-3.1-flash-lite`, the model the owner
chose after the Google project was replaced (new projects are not offered
`gemini-2.5-flash`).

**Model change to `gemini-3.1-flash-lite`, same day** (5 runs against
`eval/baseline_scores.json`, measured on 2.5 Flash): entity recall 100.0
(+0.0), quantity 80.0 (+5.0, band 12.5), food identity 82.6 (+5.3),
decomposition within tolerance for all six dishes (worst: chicken biryani
-20.2% against +/-25%). PASS. Memory evals on the same model: curator 19/19
in 8 of 8 runs after a prompt fix, coaching restrictions 12/12 and memory
requests 6/6 in 8 of 8 runs. Not run: the ingredient-replace gate, and any
measure of coaching answer quality beyond restrictions.

**Not measured**: cold start after idle, and latency from the Railway
container.

The sections below were written from the docs before these measurements.

## R1. Is it a drop-in replacement?

**Decision**: No. Same request idea, different transport. Replace the SDK with
a thin `httpx` client.

| | Jev today | GLiDE |
|---|---|---|
| Endpoint | `api.typesafe.ai/v1/systemone` via `typesafe-sdk` | `https://api.fastino.ai/v1/systemone`, plain HTTP |
| Auth | `Authorization: Bearer $TYPESAFE_API_KEY` | `X-API-Key: $FASTINO_API_KEY` |
| Model | `jev-latest` | `fastino/GLiDE` (required; response echoes `glide`) |
| Response | SDK objects: `response.choices[k]`, `response.nouls[k]` | JSON: `answers[k]` with `type`, `noul` / `choice` + `probabilities` |
| Extra body fields | tolerated by SDK | `422 Extra inputs are not permitted` |
| Retryable | 429, 529 | 425 (warming), 429, 503 |

**Rationale**: Fastino publishes no Python SDK for System One; the docs say to
use "your HTTP client". `httpx` is already a direct dependency.

**Alternative rejected**: pointing `AsyncTypeSafeClient(base_url=...)` at
Fastino. The SDK parses a different response shape and sends a Bearer header;
it would work by accident at best and keeps a dependency on a product we are
leaving.

## R2. Do the current questions pass GLiDE's validation?

**Decision**: Send them unchanged first; flatten only if rejected.

- `reports_food` (Noul with string `true`/`false` criteria): valid per docs.
- `needs_guidance` (Noul, no criteria): valid; criteria are optional.
- `intent` (Choice): **at risk.** Two of its three options are objects
  (`covers` / `excludes` / `examples`), and the docs describe Choice criteria as
  "object mapping option keys to descriptions". The OpenAPI schema decides.

**If nested options are rejected**: render each as one string, "Covers: … 
Excludes: … Examples: a; b; c". That is a wording change, so the routing gate
must pass on the flattened form (constitution V), and the holdout unit test
(no criteria text equals an eval case) keeps applying.

**Unverified**: the skill file says `fastino/glide`, the docs say
`fastino/GLiDE`. Step 1 tries the docs' spelling and records which is accepted.

## R3. Latency and cold starts

**Decision**: Keep the reply-path rules from 001: 0.8 s wait, no retries, any
failure means Gemini routes. Go/no-go is measured, not assumed.

- Jev measured p95 346 ms sequential, about 800 ms at 10 concurrent. GLiDE has
  no published latency figure. This is the largest unknown in the move.
- Docs: a cold model can answer `425 model_warming` and need about 60 s. On the
  reply path a 425 is treated like any other failure. The existing startup
  `warm_up()` stays, with a longer timeout and a bounded retry on 425, so a
  fresh deploy does not start cold.
- Docs recommend a 300 s read timeout. Not applicable to the reply path; the
  background memory judge (R8) can afford seconds, not minutes.
- If the service scales to zero when idle, low-traffic hours could send most
  messages to Gemini. SC-004 (≥ 90% decided by the judgment) catches this in
  production traces.

**Alternative rejected**: raising the routing timeout to fit GLiDE. It would
trade every user's wait for provider convenience (constitution IV).

## R4. Thresholds

**Decision**: Re-derive `intent_min_probability` and
`log_offer_min_probability` from GLiDE's scores on the eval set; record the
distribution in this file when measured.

**Rationale**: calibration is model-specific; the docs say the same. Current
values (0.75 and 0.7) were set from a Jev probe where 33 of 35 messages scored
≥ 0.95.

## R5. Cutover and rollback

**Decision**: One provider at a time. No runtime switch between Jev and GLiDE.

- Comparison happens in the eval gate on the branch, against Jev's recorded
  result (100% on 88 cases, PR #27), not in production. No Jev baseline file
  was ever committed; the GLiDE result is committed as
  `eval/baseline_intent_glide.json`.
- Rollback: unset `FASTINO_API_KEY` in Railway (Gemini routes every message,
  the pre-001 behaviour, correct but slower and it spends Gemini quota), or
  redeploy the previous release.

**Alternative rejected**: a `provider:` tunable keeping both clients. Two code
paths, two keys and two sets of thresholds to keep in step, for a rollback the
key already provides.

## R6. Recorded field names

**Decision**: Keep the stored keys (`needs_guidance_jev`, `certainty`,
`raw_choice`, `reports_food`) and add `judge_model` to the routing record and
the Logfire span.

**Rationale**: `coaching_turn.routing` is JSONB already holding the old keys;
renaming would split one series into two for every later analysis. A model tag
separates before from after (FR-006).

## R7. Cost

**Decision**: Record `usage.input_tokens` on the routing span; no budget gate.

- $0.15 per million input tokens, output free. `input_tokens` sums one internal
  pass per question, so three questions cost roughly three times the prompt.
- The Jev test fixture shows about 700 input tokens per routing request. At
  that size, 1,000 messages cost about $0.11. Real GLiDE token counts come from
  step 1.
- `402` (credits or an owner-set spend limit) is not retried; Gemini routes.
  Unlike the Gemini cap (issue #59), running out here degrades routing to the
  safety net, it does not take chat down.

## R8. The memory save decision

**Decision**: Port `agent/memory_judge.py` (branch `feat/preference-memory`) to
the shared client after this feature merges into `feat/android-app`.

**Rationale**: it was built on the TypeSafe SDK one day before this decision
and has never run live, so its questions and its 0.6 threshold get tuned on
GLiDE directly. Doing it inside this feature would entangle two unmerged
branches.

## R9. Data handling

**Decision**: Same payload as today: the message text only. One open owner item.

- Fastino becomes a processor of user message text in place of TypeSafe.
- The OpenAPI lists `GET /v1/inferences` and per-inference feedback, which
  suggests requests are stored on Fastino's side. **Owner to check** retention
  and whether storage can be disabled, and to update the privacy notice if it
  names TypeSafe.
- Logfire's `httpx` instrumentation must not capture request bodies for this
  client, and error logging keeps to exception class names (001 FR-015).
