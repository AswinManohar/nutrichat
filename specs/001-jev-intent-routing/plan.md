# Implementation Plan: Calibrated Intent Routing

**Branch**: `001-jev-intent-routing` (spec directory; no git branch created yet) | **Date**: 2026-09-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-jev-intent-routing/spec.md`

## Summary

Replace the orchestrator's log-vs-coaching router (three keyword lists, then a
Gemini classifier that costs a usage credit) with one TypeSafe Jev request per
fresh message. The request asks three questions at once: which handler to use,
whether the message also reports food, and whether it needs guidance. Jev's
answer is acted on when its certainty is at least 0.75. Below that bar, or when
Jev is unavailable, the existing Gemini classifier decides, and no path costs a
usage credit. The keyword lists are deleted. The Jev request starts before the
conversation-state load and runs alongside it, so routing is off the critical
path. Coaching replies to messages that also report food end with a
code-appended offer to log. Jev's `needs_guidance` value is only recorded next
to Gemini's in the existing `coaching_response.parsed_query` JSONB, with no
migration. Live probes: 32/32 routing, 18/18 `reports_food`, p50 274 ms
sequential. Concurrency slows Jev to about 800 ms, which is the main risk
([research R5](research.md#r5--timeout-and-retries)).

## Technical Context

**Language/Version**: Python 3.13 (`requires-python >=3.13`; CLAUDE.md still says 3.12)

**Primary Dependencies**: FastAPI, LangGraph, langchain-google-genai (Gemini second opinion), pydantic-ai (coaching), Logfire; **new**: `typesafe-sdk` 0.6.x (adds `msgspec`; `httpx2` already present)

**Storage**: No schema change. Routing record for coaching turns stored under `routing` inside the existing `coaching_response.parsed_query` JSONB (Supabase Postgres)

**Testing**: pytest + pytest-asyncio with `unittest.mock` (existing pattern: patch module-level clients); `eval/gate.py` for the live quality gate (N ≥ 5 runs, CI-based tolerance)

**Target Platform**: Linux containers on Railway (`web`, `bot` services, region `sfo`); DB in `eu-central-1`

**Project Type**: Web service backend (web frontend and Telegram bot unaffected; response shape unchanged)

**Performance Goals**: Jev p50 < 300 ms / p95 < 800 ms from `sfo` (SC-003); cue-less meal messages ≥ 300 ms faster to card (SC-004); cue-bearing ones ≤ +50 ms (SC-005)

**Constraints**: Judgment wait ≤ 0.8 s, no retries (FR-007); outage adds ≤ 0.8 s + Gemini (SC-006); message text only leaves the system (FR-015); no usage credit on routing (FR-005); no migration (branch numbering conflict with the Android line)

**Scale/Scope**: Early-stage user base; one Jev request (~700 input tokens, ≈ $0.00003) per fresh text message; ~7 backend files, ~4 test files, eval set grows from 14 to ≥ 60 cases

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unfilled template: it has no
ratified principles, so no constitutional gate can fail. In its place, the plan
is checked against the rules in `.claude/CLAUDE.md` and the user's standing
preferences recorded in project memory:

| Rule | Status (pre-design) | Status (post-design) |
|---|---|---|
| All I/O async; no blocking calls in async code | Pass: async client | Pass: `AsyncTypeSafeClient`, judgment runs as an `asyncio` task |
| Pydantic for data crossing a boundary, `extra="forbid"` | Pass | Pass: `RoutingJudgment`, `RouteDecision`, `TypeSafeConfig` |
| Type annotations, Google docstrings, `from __future__ import annotations` | Pass | Pass |
| Specific exceptions, never bare `except` | Pass | Pass: catches `TypeSafeError`, `KeyError`; re-raises `CancelledError` |
| No imports inside function bodies unless documented | Pass | Pass |
| Black / Ruff defaults | Pass | Pass |
| Quality is negotiable but never unmeasured (latency project rule) | Pass: spec sets gates | Pass: legacy baseline before deletion, CI-based gate, per-path split |
| Never commit/push to production branch without explicit say-so | Needs action | Feature branch `001-jev-intent-routing` created from `andorid_prod` (master is 187 commits behind) |
| Plans filed as GitHub issues (work style) | Note | Offer after `/speckit-tasks` (GitHub MCP server failed to connect this session; `gh` CLI can be used instead) |

No violations, so Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-jev-intent-routing/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0: R1–R11 decisions
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1: validation scenarios 1–7
├── contracts/
│   ├── jev-routing-request.md   # outbound TypeSafe request/response + failure contract
│   └── chat-response.md         # user-facing response: shape unchanged, behaviour deltas
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/backend/
├── agent/
│   ├── system_one.py          # NEW: Jev client, the three questions, judge_message() -> RoutingJudgment | None
│   ├── orchestrator.py        # CHANGED: keyword lists + quota removed from routing; RouteDecision;
│   │                          #   judgment task started before aget_state(); offer appended; routing span
│   ├── coaching.py            # unchanged (routing record goes straight to coaching_store)
│   └── coaching_store.py      # CHANGED: save_coaching_response(routing=...) → parsed_query["routing"]
├── config/
│   ├── __init__.py            # CHANGED: TypeSafeConfig; RoutingConfig loses 3 keyword fields
│   └── tunables.yaml          # CHANGED: new typesafe: block; routing.*_signals deleted
├── main.py                    # CHANGED: startup warning when TYPESAFE_API_KEY unset
└── telegram/bot.py            # CHANGED: same startup warning

tests/
├── conftest.py                # CHANGED: pop TYPESAFE_API_KEY
├── test_system_one.py         # NEW: question shape, certainty math, failure → None, holdout rule
├── test_orchestrator.py       # CHANGED: keyword tests replaced by path tests
├── test_orchestrator_quota.py # CHANGED: routing never consumes credit
└── test_coaching_store.py     # CHANGED: routing key persisted

eval/
├── cases/intent_routing.jsonl # CHANGED: 14 → ≥ 60 real cases, category + expect_offer
├── gate.py                    # CHANGED: --only, per-category + per-path report, offer scoring
├── baseline_intent_legacy.json  # NEW: today's router on the new set (before deletion)
└── probe_jev_latency.py       # NEW: sequential + concurrent latency probe

pyproject.toml / uv.lock       # typesafe-sdk
.env.example, docs/deployment/{deploy-guide,railway}.md, .claude/CLAUDE.md  # env var + stack row
```

**Structure Decision**: Existing single backend layout under `src/backend/`.
One new module, `agent/system_one.py`, keeps everything TypeSafe-specific (client,
question wording, answer parsing) in one place. Later Jev judgments, such as
USDA selection or card replies, can be added there without touching the
orchestrator. The orchestrator owns only the decision rule.

## Delivery order (for `/speckit-tasks`)

1. Feature branch off `andorid_prod` (done). The user's uncommitted USDA and
   eval edits, including `eval/gate.py`, are carried over in the working tree
   and never staged by this feature.
2. Expand the eval set to ≥ 60 real cases, add `--only` and the per-category
   report to the gate, and **record the legacy baseline** (FR-012). No routing
   code changes before this lands.
3. Latency probe script. Run it from the dev machine and from the `sfo`
   container. This is the **go/no-go** gate (SC-003). If p50 is over 500 ms,
   stop and fall back to the ticket 08 flash-lite change.
4. `system_one.py`, config, and tests (Story 1–3 core).
5. Orchestrator: move routing onto the judgment path, remove the keyword lists
   and routing quota, and run the judgment in parallel with `aget_state`
   (Story 1–4).
6. Offer to log (FR-002a) and the routing record in `parsed_query` (Story 5).
7. Gate run, outage drill, end-to-end on web and Telegram (quickstart 3, 5, 6).
8. Docs and env; set `TYPESAFE_API_KEY` on Railway `web` and `bot`. Deploy
   only with explicit approval.

## Complexity Tracking

No constitution violations, so nothing to justify.
