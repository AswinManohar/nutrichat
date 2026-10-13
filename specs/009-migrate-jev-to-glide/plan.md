# Implementation Plan: Move routing judgments from TypeSafe Jev to Fastino GLiDE

**Branch**: `feat/preference-memory` (owner decision 2026-10-13: migrate on the memory branch and ship both together) | **Date**: 2026-10-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/009-migrate-jev-to-glide/spec.md`

## Summary

Replace the TypeSafe SDK call in `agent/system_one.py` with a thin `httpx`
client for Fastino's `POST /v1/systemone`, keeping the three routing questions,
the decision rule, the 0.8 s wait and the Gemini safety net exactly as they
are. GLiDE is not a drop-in: auth header, model name, response shape and
retryable statuses differ, and thresholds must be re-derived. The move is
gated on three live measurements that have not been taken yet: the API accepts
our request, the routing gate holds, and latency from the Railway container
meets the bar Jev met.

## Technical Context

**Language/Version**: Python 3.13

**Primary Dependencies**: FastAPI, `httpx` (already a direct dependency),
Pydantic 2, Logfire. Removes `typesafe-sdk` (and its transitive `httpx2`).

**Storage**: none new. One extra key in the existing `coaching_turn.routing`
JSONB value. No migration.

**Testing**: pytest (`tests/test_system_one.py`, `tests/test_orchestrator.py`),
`eval/gate.py --only intent_routing`, new `eval/probe_glide.py`.

**Target Platform**: Railway `web` and `bot` services; outbound HTTPS to
`api.fastino.ai`.

**Project Type**: web service (backend only; no client changes).

**Performance Goals**: routing judgment p50 < 300 ms, p95 < 800 ms from the
Railway container at concurrency 1 (same bar as 001 SC-003).

**Constraints**: one attempt, 0.8 s, no retries on the reply path; only the
message text leaves the backend; nothing logged but status codes and exception
class names.

**Scale/Scope**: one request per fresh text message. About 6 source files, 4
test files, 2 eval scripts, 5 docs.

**Unverified at planning time** (live probe was blocked in the planning
session; see research.md): request acceptance incl. nested Choice criteria and
model spelling (R2), latency and cold-start behaviour (R3), score distribution
(R4), real token counts (R7). Step 1 below resolves the first; steps 5–7 the
rest. None is a design unknown: each has a decided fallback or a go/no-go.

## Constitution Check

*GATE: passed before Phase 0; re-checked after Phase 1 design: still passes.*

| Principle | Status | How |
|---|---|---|
| I. Live product | Pass | No schema or data-format change, so the branch is safe against any database. Tests use a throwaway DB. Docs updated without emojis. |
| II. Single source of truth | Pass | One provider, one config block (`glide:`), thresholds only in tunables. Question text lives in `system_one.py` and is mirrored in the contract, as today. No dual-provider switch (research R5). |
| III. Confirm before write | Pass | Untouched. Pending-card turns still bypass routing. |
| IV. Latency and cost | Pass, gated | Table below. Same single request, concurrent with state load. Fails open to Gemini. Go/no-go measured from the container before shipping. |
| V. Measured agent changes | Pass, gated | Model change, so the routing gate must pass and thresholds are re-derived from measured scores. The GLiDE result is committed as a new baseline with the numbers recorded here. |
| VI. Gated production | Pass | Ships via `/ship`. Key goes into Railway variables, never the repo. No migration. |

**New LLM provider** (Engineering Standards require a Complexity Tracking
entry): see below.

### Chat-turn budget (Principle IV)

| Per fresh message | Jev today | GLiDE | Effect |
|---|---|---|---|
| Judgment requests | 1 | 1 | none |
| Runs concurrently with state load | yes | yes | none |
| Wait limit, retries | 0.8 s, 0 | 0.8 s, 0 | none |
| Typical judgment time | p95 346 ms (measured) | **unknown** | go/no-go in step 6 |
| Model round trips (Gemini) | 0 when certain, 1 when unsure or unavailable | same rule | depends on GLiDE's certainty spread and availability; SC-004 ≥ 90% judged |
| Prompt tokens to Gemini | unchanged | unchanged | none |
| Cost per 1,000 messages | provisional TypeSafe credits | about $0.11 at ~700 input tokens (docs price; real count in step 1) | recorded per turn |
| Cold start | handshake only (warm-up at startup) | possible `425` for ~60 s | warm-up retries once; reply path falls to Gemini |

## Project Structure

### Documentation (this feature)

```text
specs/009-migrate-jev-to-glide/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/glide-routing-request.md
└── tasks.md             # /speckit-tasks, not created here
```

### Source Code (repository root)

```text
src/backend/
├── agent/
│   ├── system_one.py        # rewrite: httpx client, JSON questions, GLiDE parsing
│   ├── orchestrator.py      # add judge_model + input tokens to record and span
│   └── coaching_store.py    # docstring: routing record keys
├── config/
│   ├── __init__.py          # TypeSafeConfig -> GlideConfig
│   └── tunables.yaml        # typesafe: -> glide:, new thresholds
└── main.py                  # warm-up task name

tests/
├── test_system_one.py       # rewrite fakes for JSON responses; failure reasons
├── test_orchestrator.py     # record/span keys
└── conftest.py              # pop FASTINO_API_KEY instead of TYPESAFE_API_KEY

eval/
├── probe_glide.py           # new: --check, --scores, latency (replaces probe_jev_latency.py)
├── gate.py                  # unchanged call site; verify
└── baseline_intent_glide.json  # new, measured

pyproject.toml · uv.lock     # drop typesafe-sdk
.env.example · README.md · .claude/CLAUDE.md
docs/architecture.md · docs/deployment/{railway,deploy-guide}.md
specs/001-jev-intent-routing/contracts/jev-routing-request.md  # "superseded by 009" note
```

**Structure Decision**: no new modules. `system_one.py` keeps its name (the
endpoint is still System One) and its public surface (`judge_message`,
`RoutingJudgment`, `warm_up`, `warn_if_unconfigured`, `ROUTING_QUESTIONS`), so
`orchestrator.py`, `gate.py` and the Telegram bot need no call-site changes.

## Order of work

Done on `feat/preference-memory` alongside the preference memory (issue #61),
so the memory judge is ported in the same change (step 10 folded in). The
client lives in a new `agent/glide.py` shared by routing and the memory judge,
rather than inside `system_one.py` as first planned. The OpenAPI schema types
Choice criteria values as any JSON value, so the nested `intent` criteria are
sent unchanged (research R2). Steps 1 and 5-7 (live probe, thresholds,
latency, gate) are still open.

1. **Probe first** (`eval/probe_glide.py --check`): one live request with the
   current questions. Confirms auth, model spelling, nested criteria, response
   shape, token count. Correct the contract from what comes back. *Stop here
   if the request cannot be made to validate.*
2. `system_one.py` on `httpx`: process-wide `AsyncClient` with the existing
   10-minute keep-alive, questions as JSON, GLiDE response parsing, failure
   reasons per the contract, warm-up with one `425` retry. Disable body capture
   for this client in Logfire.
3. Config rename (`glide:` block, `GlideConfig`), `FASTINO_API_KEY`,
   `judge_model` and token count on record and span.
4. Tests rewritten for JSON responses; full suite green.
5. Score pass over the 88 eval cases (`--scores`); set both thresholds; record
   the distribution in research.md R4.
6. Latency probe locally and from the Railway container, including one run
   after 15 idle minutes. **Go/no-go** per SC-002.
7. Routing gate, 5 runs; commit `eval/baseline_intent_glide.json` with the
   result recorded in this plan. Needs Gemini (blocked while the spend cap of
   issue #59 is active).
8. Remove `typesafe-sdk`, `eval/probe_jev_latency.py`, `TYPESAFE_API_KEY`
   references; update docs and CLAUDE.md.
9. Ship: add `FASTINO_API_KEY` to Railway `web` and `bot`, `/ship`, watch
   SC-004 for a day, then delete `TYPESAFE_API_KEY` from Railway.
10. Follow-up on `feat/preference-memory`: port `agent/memory_judge.py` to the
    shared client and tune its threshold on GLiDE (research R8, issue #61).

## Risks

| Risk | Consequence | Mitigation |
|---|---|---|
| GLiDE slower than 0.8 s or often cold | Most messages fall to Gemini: slower turns, more Gemini spend against a capped budget | Step 6 go/no-go before shipping; SC-004 after |
| Nested Choice criteria rejected | Wording change to the intent question | Flatten to strings; gate must still pass |
| Calibration differs | Wrong share of second opinions, missed log offers | Step 5 re-derives thresholds |
| Requests stored by Fastino | Privacy notice out of date | Owner checks retention (research R9) before step 9 |
| Fastino credit or spend limit hit (`402`) | Routing degrades to Gemini, silently | Error-level log on 4xx; SC-004 alert |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| New LLM provider (Fastino) | Owner decision to move the judgment model; it replaces TypeSafe one for one, so the provider count does not grow | Staying on Jev: rejected by the owner. Reusing the TypeSafe SDK against Fastino: different auth and response shape (research R1) |
