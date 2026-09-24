# Research: Calibrated Intent Routing

**Date**: 2026-09-21 · **Spec**: [spec.md](spec.md)

Every item below was an unknown when planning started. Evidence comes from three
places: the live TypeSafe docs and the installed SDK's types (v0.6.0), two
throwaway live probes run from the dev machine, and the project's own latency
notes (`.scratch/logging-latency/map.md`).

## R1 — Which judgments, in how many requests?

**Decision**: One request per fresh message, three questions over the same
state `{"message": <text>}`:

| Question id | Type | Consumed by |
|---|---|---|
| `intent` | Choice: `log_meal` / `coaching` / `other` | the route |
| `reports_food` | Noul | the offer to log (FR-002a), coaching route only |
| `needs_guidance` | Noul | recorded only (FR-014) |

**Rationale**: TypeSafe evaluates all questions in a request in parallel
("speculative fan-out"), so the two Nouls add tokens but no wait.
`reports_food` and `needs_guidance` only matter when the route is coaching;
code ignores them otherwise. Live probe 1 (35 messages × 3 runs): `intent`
32/32 scored cases correct, identical across runs. Live probe 2 (18 messages):
`reports_food` 18/18, mixed messages 0.83–0.98, pure questions ≤ 0.03.
`needs_guidance` separated data readbacks (0.11–0.32) from recommendations
(0.92–0.98).

**Alternatives considered**: A fourth Choice option `log_and_ask` for mixed
messages — rejected: it splits probability with `coaching` and lowers routing
certainty on exactly the messages that are already routed correctly. A second
request for `reports_food` after routing — rejected: a serial round trip for
something the first request can answer free.

## R2 — How is routing certainty computed?

**Decision**: `p_log = probabilities["log_meal"]`; route is `log_meal` when
`p_log >= 0.5`, else `coaching`; certainty is `max(p_log, 1 - p_log)`. The
SDK's own `confidence` field is recorded but not used for gating.

**Rationale**: `coaching` and `other` share a handler. Probability split
between them ("thanks, and is rice ok?") is not routing uncertainty, and the
SDK's `confidence` — a statistic over all three options — would read low there.
The TypeSafe confidence guide explicitly supports deriving your own measure
from `probabilities`. Probe 1: "hi" and "thanks!" chose `other` with handler
certainty 1.00.

**Alternatives considered**: Two-option Choice without `other` — rejected:
greetings then have no correct answer, and the docs advise a no-match option.

## R3 — Where is the certainty bar, and what happens below it?

**Decision**: `intent_min_probability: 0.75` in tunables. Below the bar, or
when the judgment is unavailable, the existing Gemini classifier
(`_intent_llm`) decides. No usage credit on any path (clarification Q4).

**Rationale**: Both misroutes are recoverable (a card the user cancels, a text
reply), so a moderate bar. In probe 1 only 2 of 35 messages fell below 0.75
("eggs?" 0.66, a prompt-injection string 0.70); everything else was ≥ 0.95, so
the bar is not sensitive between roughly 0.72 and 0.94 on current evidence.
It must be re-examined on the 60+ real-message set (FR-011).

**Alternatives considered**: Acting on Jev's best guess when unsure — rejected
in clarification Q2. Keyword lists as the outage path — rejected in Q1/Q2.

## R4 — Where in the turn is the judgment requested?

**Decision**: In `handle_message`, start the judgment as a task *before*
`graph.aget_state()` and await it after. If the graph is paused, cancel the
task and ignore it. Do not start it at all when a photo is attached or the text
is empty.

**Rationale**: `aget_state` costs one or more transatlantic DB round trips
(≥ 145 ms each; ~290 ms per checkout after the health-check fix), and the
judgment took p50 274 ms sequentially from the dev machine. Overlapping them
takes routing off the critical path for every fresh message, which is how
SC-005 (no regression on messages that were instant via keywords) is met after
the keywords are deleted. A wasted judgment on a paused turn costs ~$0.00003.
This is only affordable because the judgment is free of quota and nearly free
of cost; it could not be done with the Gemini classifier.

**Alternatives considered**: Request after `aget_state` — simpler, but adds
~270 ms to every fresh turn, failing SC-005. Request in parallel with
extraction — larger gain, but wastes a Gemini extraction call on every coaching
turn; out of scope.

## R5 — Timeout and retries

**Decision**: Per-attempt HTTP timeout `request_timeout_s: 0.8`, SDK
`RetryPolicy(max_retries=0)`. Any `TypeSafeError` (includes timeout,
connection, rate-limit, auth, validation) or a missing answer key means
"unavailable" → Gemini.

**Rationale**: FR-007 forbids stacking retries in front of the user; SC-003's
p95 target is 800 ms, so anything slower is treated as a miss. SC-006's bound is
then 0.8 s + Gemini (~0.63 s) ≈ 1.4 s.

**Risk found**: probe 2 sent 10 requests concurrently on one client and saw
p50 **799 ms** / max 852 ms, versus 274 ms sequential. Cause not yet known
(per-key queueing, connection reuse, or server-side batching). At a 0.8 s
timeout this would push a large share of concurrent requests to the Gemini
path. Consequences: (a) the production latency probe (R9) MUST measure at
concurrency 1, 5 and 10; (b) the eval gate runs at concurrency 5 and must
record how many cases were decided by which path, otherwise a "pass" could be
Gemini's accuracy, not Jev's; (c) the timeout stays a tunable.

## R6 — The offer to log (FR-002a)

**Decision**: Code appends a fixed sentence to the coaching reply when the route
is coaching and `reports_food >= log_offer_min_probability` (0.7):
*"Want me to log that? Send me what you had and I'll add it."* The sentence is a
tunable string. When the judgment is unavailable, no offer is made.

**Rationale**: SC-011 asks for ≥ 90% of mixed messages to end with the offer and
≤ 5% of pure questions to get one. A code-owned suffix makes that depend only on
the Noul (18/18 in probe 2), not on the prose model obeying an instruction, and
it costs no extra tokens or prompt changes. A bare "yes" reply is then an
ordinary fresh message, as the spec's edge case states. The offer is appended
after citations are extracted so it cannot disturb `[n]` parsing, and is part of
the text saved to coaching history and `coaching_response.response_text`.

**Alternatives considered**: Prompt instruction so the coach names the food
("Want me to log the pizza?") — nicer copy, but unmeasurable variance and a
change to the coaching prompt, which has its own eval. Can be revisited later.

## R7 — Where is the routing record kept (FR-010, FR-014)?

**Decision**: Two places. (1) Logfire span `route_message` on every fresh
message with attributes `path` (`judgment` / `second_opinion_unsure` /
`second_opinion_unavailable`), `intent`, `certainty`, `raw_choice`,
`reports_food`, `needs_guidance_jev`, `failure` and `judgment_ms`.
(2) For coaching turns, the same values are stored under a `routing` key inside
the existing `coaching_response.parsed_query` JSONB.

**Rationale**: The project has no Logfire read key, so agreement between Jev's
and Gemini's `needs_guidance` (SC-010) has to be computable from the database.
`parsed_query` is written from a dict and is only ever passed through
(`export_feedback.py` copies it verbatim; nothing re-validates it into
`QueryParsed`), so an extra key needs **no migration** and automatically lands
in the feedback JSONL export next to Gemini's `needs_guidance`. Avoiding a
migration matters here: migration numbering already diverges between branches
(014 on this line, 012/013 on the Android branch).

**Alternatives considered**: New nullable `routing` column — cleaner, rejected
for the migration conflict. Spans only — rejected: not queryable without a read
key.

## R8 — What is deleted?

**Decision**: `routing.log_signals`, `routing.query_signals`,
`routing.weak_query_signals` (tunables + `RoutingConfig` fields), the three
frozensets and the keyword block in `orchestrator._classify_intent`, the
`consume_llm_credit` call in the intent path, and the tests that assert keyword
behaviour (`tests/test_orchestrator.py` keyword/`assert_not_called` tests,
`tests/test_orchestrator_quota.py::test_classify_intent_*`). The card-reply
keyword lists (`confirm_keywords`, `reject_keywords`, `new_meal_*`) are a
different classifier and stay. `prompts/intent_system.md` stays (Gemini second
opinion).

**Ordering constraint**: FR-012 requires today's router to be measured on the
expanded eval set *before* deletion; that baseline is committed first.

## R9 — Evaluation and the go/no-go gate

**Decision**:
- Expand `eval/cases/intent_routing.jsonl` to ≥ 60 cases with a `category`
  field (`bare_food`, `bare_food_nutrient_word`, `explicit_report`,
  `food_question`, `data_question`, `advice`, `non_english`, `smalltalk`,
  `mixed`), sourced from real `meal_log` / `coaching_response` text. `mixed`
  cases also carry `expect_offer: true`; pure questions `expect_offer: false`.
- `score_intent_routing` reports accuracy per category and the share of cases
  decided by each path. Tolerance tightens from 8.0 to what N=60 supports
  (1.7 pp granularity), via the existing `_validate_tolerances` rule.
- New `eval/probe_jev_latency.py`: sequential and concurrent (1/5/10) latency
  with the real questions; run once from the dev machine and once inside the
  Railway `web` container via `railway ssh` (FR-013, SC-003).
- Examples embedded in the Jev question criteria are kept disjoint from the
  eval cases; a unit test asserts the intersection is empty (FR-011).

**Note**: `eval/gate.py` has uncommitted user changes on this working tree; the
gate edits must be made on top of those, not against HEAD.

## R10 — Dependency and configuration

**Decision**: Add `typesafe-sdk` (0.6.x) via `uv add`. API key from
`TYPESAFE_API_KEY` (read with `os.environ`, matching the project's existing
per-module pattern). New `typesafe:` block in `tunables.yaml` + `TypeSafeConfig`
model: `model`, `intent_min_probability`, `log_offer_min_probability`,
`log_offer_text`, `request_timeout_s`. No `enabled` flag: removing the key is
the off switch (every message then takes the Gemini path, FR-008). Missing key
is logged once at startup by `web` (FastAPI lifespan) and `bot`.

**Facts checked against the installed SDK, because the docs disagree with
themselves**: responses expose `response.choices[...]`, `response.nouls[...]`
(typed views) as well as `response.answers[...]`; `ChoiceAnswer` has `choice`,
`confidence`, `probabilities`; `NoulAnswer` has `noul`; all errors derive from
`TypeSafeError`; the client takes `api_key`, `model`, `timeout`, `retry`.
The SDK pulls in `httpx2` (pydantic org, already present in this venv) and
`msgspec`. The SDK's first release was 2026-09-09; pin a compatible range and
expect churn.

**Test hermeticity**: `tests/conftest.py` removes `TYPESAFE_API_KEY` from the
environment so an exported key can never send the suite to the network.

## R11 — Privacy

**Decision**: Only the message text is sent (FR-015) — no user id, no history.
No in-app privacy page enumerating processors was found in `frontend/src`, so
no copy change is needed in the product; the deployment docs gain the new env
var and a one-line note that message text is sent to TypeSafe for routing.

## Open items carried into tasks (not blockers for design)

- Jev latency from the Railway `sfo` container, including under concurrency (R5).
- Whether 0.75 is the right bar on real messages (R3).
- SC-009 needs a pre-launch baseline of "coaching reply immediately followed by
  the same food re-sent"; compute it from `coaching_response` + `meal_log`
  timestamps before enabling.

## R12 — Measured latency (2026-09-21)

**Dev machine** (`eval/probe_jev_latency.py --n 40`, warm connection):

| Concurrency | p50 | p95 | max | input tokens |
|---|---|---|---|---|
| 1 | 287 ms | 512 ms | 523 ms | 834 |
| 5 | 281 ms | 658 ms | 665 ms | 834 |
| 10 | 274 ms | 679 ms | 743 ms | 834 |

The earlier "10 concurrent ≈ 800 ms" reading (R5) did not reproduce.

**Idle gaps** (same client, one call after each gap):

| Setup | cold | warm | 8 s | 20 s | 60 s | 120 s |
|---|---|---|---|---|---|---|
| SDK default (httpx keepalive 5 s) | 711 | 247 | 600 | 679 | 688 | — |
| keepalive_expiry 600 s | 643 | 275 | 262 | 856* | 259 | 280 |

\* single outlier. Decision: 10-minute keepalive plus a startup warm-up
request with its own 10 s timeout (`system_one.warm_up`). Without it, a
low-traffic app pays a TLS handshake on most messages and, at a 0.8 s timeout,
often falls back to Gemini.

**Container (`sfo`)**: not yet measured, needs the user (T010). This is still
the go/no-go number for SC-003.

## R13 — Gate result

`eval/gate.py --only intent_routing --runs 5 --baseline eval/baseline_intent_legacy.json`:
100.0% in all 5 runs vs legacy 77.3% (+22.7 pp, PASS). Decided by judgment
98.9%, second opinion (unsure) 1.1%, unavailable 0%. Offer to log: recall 100%,
false offers 0%. Every category 100%, including bare_food_nutrient_word
(legacy 10.5%) and mixed (legacy 62.5%).

## R14 — Message-to-card latency, local A/B (2026-09-24, T033)

Two backends against the same local DB and Redis: the pre-Jev commit `17d143f`
on :8001 and this branch on :8000. 3 runs x 24 messages, sequential, a fresh
user id per request. Raw data: `logs/bench_jev_vs_legacy.json`.

| Message type | Legacy p50 | Jev p50 | Delta |
|---|---|---|---|
| Cue-less meal (10 msgs) | 2,093 ms | 1,619 ms | **-474 ms** (SC-004 target >= -300: pass) |
| Cue-bearing meal (8 msgs) | 1,579 ms | 1,708 ms | +129 ms (SC-005 target <= +50: **not met locally**) |
| Meal with a nutrient word (3 msgs) | 7,459 ms, coaching reply (misroute) | 1,261 ms, meal card | fixed |
| Question (3 msgs) | 3,506 ms | 3,218 ms | noise |

SC-005 note: locally the checkpoint read is ~1 ms, so the Jev call has nothing
to overlap with and lands on the critical path where the keyword match was free.
In production that read is a ~300 ms transatlantic round trip (R4), so the
overlap should absorb most of it. Re-measure in the container before calling
SC-005 either way. The user was also clicking through the :8000 UI during the
run, which adds noise to the Jev column only.
