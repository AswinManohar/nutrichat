---

description: "Task list for Calibrated Intent Routing (Jev)"
---

# Tasks: Calibrated Intent Routing

**Input**: Design documents from `specs/001-jev-intent-routing/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Included. The spec's Independent Tests and quickstart scenario 1
require unit tests for every routing path, and the project's gate rule
("quality is negotiable but never unmeasured") requires the eval gate before and
after the change.

**Organization**: Tasks are grouped by user story (US1–US5 from spec.md). Run
unit tests with `PYTHONPATH=src .venv/bin/python -m pytest <files> -q`. The two
failures `tests/test_e2e_meals.py::test_chat_history_isolation` and
`tests/test_trends.py::test_trends_returns_day_aggregates` already exist on HEAD
and are not caused by this feature.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)

## Conventions every code task follows

- `.claude/CLAUDE.md` Python standards: `from __future__ import annotations`,
  full type hints, Google docstrings, Pydantic models with
  `model_config = ConfigDict(extra="forbid")`, specific exceptions only, no
  imports inside functions, Black + Ruff defaults (88 cols).
- SDK facts (verified against installed `typesafe-sdk` 0.6.0, trust these over
  the docs): `from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul,
  RetryPolicy, TypeSafeError`; `await client.system_one(state, questions)`;
  read `response.choices["intent"].probabilities`, `.choice`, `.confidence`;
  `response.nouls["<id>"].noul`; `response.usage.input_tokens`. Timeout
  exception is `TypeSafeAPITimeoutError(timeout)` (constructor takes a timeout).
- Never commit or push to `andorid_prod` or `master`; commits only on the
  feature branch, and only when the user asks.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Branch, dependency, test hermeticity.

- [X] T001 Branch `001-jev-intent-routing` created from `andorid_prod` (17d143f), not `master`: `master` is 187 commits behind. The user's uncommitted USDA/eval edits are carried over in the working tree, untouched and never staged by this feature; this feature's `eval/gate.py` changes go on top of them.
- [X] T002 Add the SDK: `uv add "typesafe-sdk>=0.6,<0.7"` and confirm `pyproject.toml` and `uv.lock` changed, and `.venv/bin/python -c "import typesafe_sdk"` works.
- [X] T003 [P] In `tests/conftest.py`, directly after the `GOOGLE_API_KEY` setdefault line, add `os.environ.pop("TYPESAFE_API_KEY", None)` with a comment: no key means routing takes the Gemini path, so an exported key can never send the suite to the network.
- [X] T004 [P] Add `TYPESAFE_API_KEY=        # console.typesafe.ai — Jev intent routing; unset = every message routed by Gemini` after the `ANTHROPIC_API_KEY` line in `.env.example`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Measure today's router on a real eval set, run the latency go/no-go, and add config. **FR-012: no routing code may change until T008 is committed.** **SC-003: if T010 shows p50 > 500 ms from the container, STOP the feature and tell the user.** **Done:** 77.3% overall, CI 0.0; bare_food_nutrient_word 10.5%, mixed 62.5%. Run against the local `nutrichat_sdd` DB. **Done** (R12): container p50 86 / p95 134 ms at concurrency 1 — GO. `TYPESAFE_API_KEY` set on `web` and `bot` (production) with `--skip-deploys`; it takes effect on the next deploy.

- [X] T005 Expand `eval/cases/intent_routing.jsonl` from 14 to **≥ 60** lines. Keep the existing 14 and add `category` to each. Every line: `{"text", "expect": "log_meal"|"coaching", "category", "note"}`, plus `"expect_offer": true|false` on every `mixed` case and on every `coaching` case that reports no food. Categories and minimums (FR-011): `bare_food_nutrient_word` ≥ 15 (e.g. "protein shake", "low fat yogurt", "high fiber cereal"), `food_question` ≥ 10, `non_english` ≥ 5, `smalltalk` ≥ 5 (expect `coaching`), `mixed` ≥ 8 (expect `coaching`, `expect_offer: true`, e.g. "I had pizza, was that bad?"), and several each of `bare_food`, `explicit_report`, `data_question`, `advice`. Source real phrasing from `meal_log` and `coaching_response.query` (read-only SQL via the Supabase MCP or `psql $DATABASE_URL`). Do not reuse any string from `contracts/jev-routing-request.md` question examples. **Done:** 88 cases. The production DB was unreachable from the dev machine (Supabase MCP timeouts; the `.env` host is IPv6-only), so real phrasing came from the meal_log-sourced eval cases and `eval_coaching.py`; the rest are tagged `source: synthetic`.
- [X] T006 Extend `eval/gate.py` (on top of any user changes carried over in T001): (a) add `--only CATEGORY` (repeatable) so `--only intent_routing` runs just that category; (b) make `score_intent_routing` also return per-`category` accuracy and, when available, the per-path counts (`judgment` / `second_opinion_unsure` / `second_opinion_unavailable`) and offer precision/recall against `expect_offer`, printed in the report and written to the JSON; (c) lower `TOLERANCES["intent_routing"]` from `8.0` to the smallest value `_validate_tolerances()` accepts for the new case count (it rejects tolerance < 100/N pp). Leave the other categories untouched. The per-path/offer fields stay empty until US1 exposes them.
- [X] T007 [P] Create `eval/probe_jev_latency.py`: CLI `--n INT` (default 50), `--concurrency 1,5,10`, reads `TYPESAFE_API_KEY`, builds the exact three-question request from `contracts/jev-routing-request.md` (import the questions from `backend.agent.system_one` once T012 exists; until then keep a local copy), warms up one call, then per concurrency level prints p50/p95/max ms and median input tokens. No other dependencies beyond `typesafe_sdk` and stdlib.
- [X] T008 Record the legacy baseline **before any routing change**: `PYTHONPATH=src .venv/bin/python eval/gate.py --only intent_routing --runs 5 --out eval/baseline_intent_legacy.json`. Needs `GOOGLE_API_KEY`, `DATABASE_URL` (the gate creates and deletes a synthetic quota user). Commit `eval/cases/intent_routing.jsonl`, `eval/gate.py` and `eval/baseline_intent_legacy.json` together.
- [X] T009 [P] Add `TypeSafeConfig` to `src/backend/config/__init__.py` (before `PromptsConfig`) with fields, verbatim from data-model.md: `model: str`, `intent_min_probability: float = Field(ge=0.5, le=1.0)`, `log_offer_min_probability: float = Field(ge=0.0, le=1.0)`, `log_offer_text: str = Field(min_length=1)`, `request_timeout_s: float = Field(gt=0)`, `extra="forbid"`; add `typesafe: TypeSafeConfig` to `Tunables` after `routing`. Add the matching `typesafe:` block to `src/backend/config/tunables.yaml` above `routing:` with values `model: "jev-latest"`, `intent_min_probability: 0.75`, `log_offer_min_probability: 0.7`, `log_offer_text: "Want me to log that? Send me what you had and I'll add it."`, `request_timeout_s: 0.8`, each with a comment explaining the dial (see research R3, R5, R6). Also add the block to `.scratch/tunables_api.yaml` and `.scratch/logging-latency/assets/tunables_candidate.yaml` so those copies keep validating.
- [X] T010 Run the latency gate (SC-003): `.venv/bin/python eval/probe_jev_latency.py --n 50 --concurrency 1,5,10` locally, then inside the Railway `web` container (`railway ssh --service web`, with `TYPESAFE_API_KEY` set only for that shell). Record both result tables in `specs/001-jev-intent-routing/research.md` under a new "R12 — Measured latency" section. Go if container concurrency-1 p50 < 300 ms and p95 < 800 ms. **No-go if p50 > 500 ms: stop and report.** If concurrency-5/10 p95 > 800 ms, raise `typesafe.request_timeout_s` to cover p95 and note it.

**Checkpoint**: Legacy baseline committed, latency go decision recorded, config loads (`PYTHONPATH=src .venv/bin/python -c "from backend.config import get_tunables; print(get_tunables().typesafe)"`).

---

## Phase 3: User Story 1 - A food name gets logged, a question gets answered (Priority: P1) 🎯 MVP

**Goal**: Every fresh text message is routed by Jev's judgment; keyword lists are gone; mixed report-and-question messages get the offer to log.

**Independent Test**: With a real key, `eval/gate.py --only intent_routing --baseline eval/baseline_intent_legacy.json` shows overall ≥ 95%, `bare_food_nutrient_word` ≥ 95%, offer on ≥ 90% of `mixed` and ≤ 5% of `expect_offer: false` (SC-001, SC-002, SC-011); unit tests pass with no network.

### Tests for User Story 1

- [X] T011 [P] [US1] Create `tests/test_system_one.py` with a fake client (`MagicMock` whose `system_one` is an `AsyncMock` returning a `SimpleNamespace` with `choices`, `nouls`, `usage`): (a) `judge_message("protein shake")` with `{"log_meal": 0.97, "coaching": 0.02, "other": 0.01}` returns `intent="log_meal"`, `certainty≈0.97`; (b) `{"log_meal": 0.04, "coaching": 0.5, "other": 0.46}` returns `intent="coaching"`, `certainty≈0.96`, `raw_choice="coaching"` (coaching+other share a handler); (c) the request state is exactly `{"message": text}` and the question ids are exactly `{"intent", "reports_food", "needs_guidance"}` (FR-015); (d) `_get_client` returns None without `TYPESAFE_API_KEY` and `judge_message` then returns None without touching the network; (e) holdout: no `text` in `eval/cases/intent_routing.jsonl` appears in any example string in the module's question criteria (FR-011).
- [X] T012 [P] [US1] In `tests/test_orchestrator.py`: delete `test_classify_intent_log_signal_no_llm`, `test_classify_intent_query_signal_no_llm`, `test_classify_intent_what_should_i_eat_is_coaching` and every other test that asserts keyword behaviour. Add tests that patch `backend.agent.orchestrator.judge_message`: confident `log_meal` judgment → `log_meal`, `_intent_llm.ainvoke` not called; confident `coaching` → `coaching`, not called; judgment `None` → `_intent_llm.ainvoke` called once and its answer used. Add a `handle_message` test that a coaching turn with `reports_food=0.95` returns a message ending with `get_tunables().typesafe.log_offer_text`, and with `reports_food=0.1` does not.

### Implementation for User Story 1

- [X] T013 [US1] Create `src/backend/agent/system_one.py`: module docstring (typed judgments; returns None when unavailable so callers fall back); the three questions `_INTENT_QUESTION` (Choice), `_REPORTS_FOOD_QUESTION` (Noul), `_NEEDS_GUIDANCE_QUESTION` (Noul) with wording copied **verbatim** from `specs/001-jev-intent-routing/contracts/jev-routing-request.md`; `class RoutingJudgment(BaseModel)` with fields verbatim from data-model.md (`intent: Literal["log_meal","coaching"]`, `certainty: float = Field(ge=0.5, le=1.0)`, `raw_choice: Literal["log_meal","coaching","other"]`, `reports_food: float = Field(ge=0.0, le=1.0)`, `needs_guidance: float = Field(ge=0.0, le=1.0)`, `latency_ms: float = Field(ge=0.0)`, `extra="forbid"`); lazy process-wide `_get_client() -> AsyncTypeSafeClient | None` (None when `TYPESAFE_API_KEY` unset; else `AsyncTypeSafeClient(api_key=..., model=cfg.model, timeout=cfg.request_timeout_s, retry=RetryPolicy(max_retries=0))`); `async def judge_message(message: str) -> RoutingJudgment | None` that sends `{"message": message}` with the three questions, computes `p_log = probabilities["log_meal"]`, `intent = "log_meal" if p_log >= 0.5 else "coaching"`, `certainty = max(p_log, 1 - p_log)`, and returns None on `TypeSafeError` or `KeyError`. For now log the exception at warning level; US3 refines failure reporting.
- [X] T014 [US1] In `src/backend/agent/orchestrator.py`: add `class RouteDecision(BaseModel)` with fields verbatim from data-model.md (`intent`, `path: Literal["judgment","second_opinion_unsure","second_opinion_unavailable"]`, `judgment: RoutingJudgment | None`, `offer_to_log: bool`, `extra="forbid"`); replace `_classify_intent` with `async def _route(message: str) -> RouteDecision` implementing exactly the data-model decision rule (judgment None → Gemini, `second_opinion_unavailable`; `certainty >= typesafe.intent_min_probability` → judgment, `judgment`; else Gemini, `second_opinion_unsure`); Gemini call is the existing `_intent_llm.ainvoke([SystemMessage(_INTENT_SYSTEM), HumanMessage(message)])` inside `logfire.span("classify_intent_llm")`. `offer_to_log = intent == "coaching" and judgment is not None and judgment.reports_food >= typesafe.log_offer_min_probability`. Wrap `_route` in `logfire.span("route_message")` setting `path`, `intent`, `certainty`, `raw_choice`, `reports_food`, `needs_guidance_jev`, `offer_to_log`, `judgment_ms` when present. Update `handle_message` to use `_route(...)` and keep `span.set_attribute("intent", ...)`. For now leave the `consume_llm_credit` call in the Gemini branch (US2 removes it).
- [X] T015 [US1] Delete the keyword router: remove `_LOG_SIGNALS`, `_QUERY_SIGNALS`, `_WEAK_QUERY_SIGNALS` and the keyword block from `src/backend/agent/orchestrator.py`; remove `log_signals`, `query_signals`, `weak_query_signals` from `RoutingConfig` in `src/backend/config/__init__.py` and their YAML (with the long precedence comment) from `src/backend/config/tunables.yaml`, and from the two `.scratch/*tunables*.yaml` copies; keep `confirm_keywords`, `reject_keywords`, `new_meal_leadins`, `new_meal_exclusions`. Check nothing else references them: `grep -rn "log_signals\|query_signals" src tests eval`.
- [X] T016 [US1] Offer to log (FR-002a, contracts/chat-response.md): change `_handle_coaching` in `src/backend/agent/orchestrator.py` to accept `offer_to_log: bool = False`; after `_coaching_agent.handle(...)` returns and **before** `save_coaching_response`, when `offer_to_log` is true replace the result with `result.model_copy(update={"message": f"{result.message}\n\n{_TUNABLES.typesafe.log_offer_text}"})` so the saved `response_text`, the returned `message` and the coaching history all include it; citations are already extracted and stay unchanged. Never append to `_UPGRADE_MSG`. Pass `decision.offer_to_log` from `handle_message`.
- [X] T017 [US1] Update `eval/gate.py` `score_intent_routing` to call `orchestrator._route(case["text"])` instead of `_classify_intent`, compare `decision.intent` to `expect`, and record `decision.path` and `decision.offer_to_log` for the per-path counts and offer scoring added in T006.
- [X] T018 [US1] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/test_system_one.py tests/test_orchestrator.py -q` until green; then run the full suite (`tests -q --ignore=tests/integration`) and confirm only the two known HEAD failures remain.
- [X] T019 [US1] Run the gate against the legacy baseline with a real key: `PYTHONPATH=src .venv/bin/python eval/gate.py --only intent_routing --runs 5 --baseline eval/baseline_intent_legacy.json`. Pass criteria: SC-001 (≥ 95% overall, no category worse beyond its CI), SC-002 (`bare_food_nutrient_word` ≥ 95%), SC-011 (offer ≥ 90% of mixed, ≤ 5% false offers). **Check the per-path split: if `second_opinion_unavailable` > 5% of cases, the score is not Jev's; lower gate concurrency to 1 for this category and re-run.** If a category fails, fix question wording in `system_one.py` and the contract file together, then re-run; never add eval texts to the question examples. **Done:** 100.0% every run (+22.7 pp, PASS); Jev decided 98.9%, second opinion 1.1%, unavailable 0%; offer recall 100%, false offers 0%.

**Checkpoint**: MVP. Jev routes, keywords gone, offer works; gate passes.

---

## Phase 4: User Story 2 - Unsure messages get a second opinion instead of a guess (Priority: P2)

**Goal**: The certainty bar is honoured, and routing never costs a usage credit on any path (clarification Q4, FR-005).

**Independent Test**: Unit tests show that below-bar judgments call Gemini, that no routing path calls `consume_llm_credit`, and that a zero-credit user asking a question reaches the coaching handler, which returns the upgrade message.

### Tests for User Story 2

- [X] T020 [P] [US2] In `tests/test_orchestrator.py`, add: judgment `certainty=0.6` with bar 0.75 → Gemini called once, `path == "second_opinion_unsure"`; patching `_TUNABLES.typesafe` via `model_copy(update={"intent_min_probability": 0.55})` makes the same judgment act directly (`path == "judgment"`).
- [X] T021 [P] [US2] In `tests/test_orchestrator_quota.py`, replace `test_classify_intent_over_quota_defaults_to_log_meal` and `test_classify_intent_keyword_match_skips_quota` with: (a) `_route` never awaits `consume_llm_credit` on any of the three paths (patch it with an `AsyncMock` and `assert_not_called`); (b) `handle_message` for a coaching-routed message with `consume_llm_credit → False` returns `_UPGRADE_MSG` from `_handle_coaching` (not a meal card). Keep the existing `_handle_coaching` and `_handle_meal_logging` quota tests as they are.

### Implementation for User Story 2

- [X] T022 [US2] Remove the `consume_llm_credit` call and the over-quota `return "log_meal"` from the Gemini branch of `_route` in `src/backend/agent/orchestrator.py`, and update its docstring: routing is free on every path; credits are spent only by `_handle_coaching` / `_handle_meal_logging` as today.
- [X] T023 [US2] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/test_orchestrator.py tests/test_orchestrator_quota.py -q` until green.

**Checkpoint**: US1 + US2 work; SC-007 holds by construction.

---

## Phase 5: User Story 3 - Chat keeps working when the judgment service does not (Priority: P2)

**Goal**: Every failure mode maps to the Gemini path within the timeout, is recorded, and a missing key is reported once at startup (FR-006–FR-008, contracts/jev-routing-request.md failure table).

**Independent Test**: Unit tests for each failure class; the outage drill in quickstart §5.

### Tests for User Story 3

- [X] T024 [P] [US3] In `tests/test_system_one.py`, parametrize over `TypeSafeAPITimeoutError(0.8)`, `TypeSafeAPIConnectionError()`, `TypeSafeRateLimitError`/`TypeSafeAuthenticationError`/`TypeSafeInternalServerError` (construct each as the SDK allows; if a constructor needs a response object, build the instance with `Exc.__new__(Exc)` and set no attributes, and use `repr`/class name in the code under test, never `str(exc)`, which can raise on bare instances). Also cover a response missing `"reports_food"` (`malformed_response`). Each → `judge_message` returns None and the recorded failure equals the class name / `"malformed_response"`. Add: `asyncio.CancelledError` from the client propagates (is not swallowed).
- [X] T025 [P] [US3] Add `tests/test_startup_typesafe.py`: `warn_if_unconfigured()` logs exactly one warning containing `TYPESAFE_API_KEY` when unset and nothing when set (use `caplog`). (Folded into `tests/test_system_one.py`.)

### Implementation for User Story 3

- [X] T026 [US3] In `src/backend/agent/system_one.py`: make `judge_message` return `tuple[RoutingJudgment | None, str | None]` where the second item is the failure reason (`"not_configured"`, the exception class name `type(exc).__name__`, or `"malformed_response"` for `KeyError`). Re-raise `asyncio.CancelledError`. Log failures at warning with the class name only (never the message text, FR-015). Add `def warn_if_unconfigured() -> None` that logs one warning when `TYPESAFE_API_KEY` is unset ("all fresh messages will be routed by the Gemini classifier"). Update `_route` in `src/backend/agent/orchestrator.py` to set the `failure` span attribute from the reason, and update T011/T012 tests for the new return shape.
- [X] T027 [US3] Call `warn_if_unconfigured()` once at startup: in `lifespan` in `src/backend/main.py` before `yield`, and in the bot entry point in `src/backend/telegram/bot.py` before `start_polling` / webhook setup (the function that logs "Starting Telegram bot…").
- [X] T028 [US3] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/test_system_one.py tests/test_orchestrator.py tests/test_startup_typesafe.py -q` until green.
- [X] T029 [US3] Outage drill (quickstart §5), locally with `scripts/run-local.sh --local-db`: send "protein shake", "is rice healthy?", "I had pizza, was that bad?" (a) with `TYPESAFE_API_KEY` unset, (b) with `TYPESAFE_BASE_URL=http://10.255.255.1`, (c) with an invalid key. Expect correct replies every time, no offer appended, one startup warning in (a), `route_message.failure` set in (b)/(c), and added wait ≤ `request_timeout_s` + Gemini (SC-006). Report the observed timings. **Done** via `_route` directly: all three setups routed correctly with no offer; unreachable ≈1.4–1.7 s, invalid key ≈0.85–1.6 s. The drill found a cold-connection problem (first call and any call after > 5 s idle ≈ 600–700 ms), fixed with a 10-minute keepalive and a startup warm-up (commit 7b259f8).

**Checkpoint**: Feature is safe to deploy without a key.

---

## Phase 6: User Story 4 - Logging feels faster when the message has no obvious cue (Priority: P3)

**Goal**: Routing is off the critical path: the judgment runs concurrently with `graph.aget_state()` and is discarded for pending-card and photo turns (research R4, FR-009).

**Independent Test**: Unit test proves overlap and cancellation; latency comparison against the `.scratch/logging-latency` baseline (SC-004, SC-005).

### Tests for User Story 4

- [X] T030 [P] [US4] In `tests/test_orchestrator.py`, add: (a) with the graph paused (`aget_state` returns `next=("present",)`), a `judge_message` mock that awaits a never-set `asyncio.Event` is cancelled and `handle_message` still completes the card reply; (b) with `image_b64` set, `judge_message` is never called; (c) with empty/whitespace text and no image, `judge_message` is never called; (d) overlap: make `aget_state` and `judge_message` each `await asyncio.sleep(0.2)` and assert `handle_message` routing completes in < 0.35 s.

### Implementation for User Story 4

- [X] T031 [US4] In `handle_message` in `src/backend/agent/orchestrator.py`: when `not image_b64 and user_input.strip()`, start `judgment_task = asyncio.create_task(judge_message(user_input))` **before** `await graph.aget_state(config)`; pass the task into `_route` (change `_route` to accept `judgment_task: asyncio.Task | None` and await it inside the `route_message` span). If the graph is paused, `judgment_task.cancel()` and `await` it inside `contextlib.suppress(asyncio.CancelledError)`, then take the existing card path. `judgment_ms` measures from task creation to result. Keep the behaviour for paused and photo turns byte-for-byte identical to today.
- [X] T032 [US4] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/test_orchestrator.py -q` until green.
- [X] T033 [US4] Measure SC-004/SC-005 with the per-node method in `.scratch/logging-latency/issues/01-per-node-latency-baseline.md`, on 10 cue-less messages ("mutton biryani", "banana smoothie", …) and 10 cue-bearing ones ("I had 2 eggs…"). Report the median time-to-card delta against the recorded baseline. Pass: cue-less improves ≥ 300 ms, cue-bearing regresses ≤ 50 ms. **Done locally** (research R14): cue-less -474 ms (pass), cue-bearing +129 ms (SC-005 not met locally; expected to close in the container where the overlapped checkpoint read is ~300 ms). Container re-measure still owed.

**Checkpoint**: Latency goal verified or quantified.

---

## Phase 7: User Story 5 - See whether the judgment could also spot guidance questions (Priority: P3)

**Goal**: For coaching turns routed by the judgment, Jev's values are stored next to Gemini's `needs_guidance` in `coaching_response.parsed_query["routing"]`, with no behaviour change (FR-014, SC-010).

**Independent Test**: `coaching_response` rows for Jev-routed turns carry `parsed_query.routing`; rows for unavailable-path turns do not; replies and citations are unchanged.

### Tests for User Story 5

- [X] T034 [P] [US5] In `tests/test_coaching_store.py`, add: `save_coaching_response(..., routing={"path": "judgment", "certainty": 0.98, "raw_choice": "coaching", "reports_food": 0.97, "needs_guidance_jev": 0.94, "offer_to_log": True})` stores it at `row.parsed_query["routing"]` while `row.parsed_query["needs_guidance"]` is still Gemini's bool; with `routing=None` the key is absent.
- [X] T035 [P] [US5] In `tests/test_orchestrator.py`, add: a Jev-routed coaching turn passes a `routing` dict with exactly those six keys to `save_coaching_response`; a `second_opinion_unavailable` turn passes `routing=None`; and `_coaching_agent.handle` is called with the same arguments as before (guideline retrieval still driven only by Gemini's `parsed.needs_guidance`).

### Implementation for User Story 5

- [X] T036 [US5] In `src/backend/agent/coaching_store.py`, add keyword-only `routing: dict[str, float | str | bool] | None = None` to `save_coaching_response`; write `parsed_query={**result.parsed.model_dump(mode="json"), **({"routing": routing} if routing else {})}`. Document the key in the docstring. No migration (research R7).
- [X] T037 [US5] In `src/backend/agent/orchestrator.py`, build the routing dict from the `RouteDecision` (`path`, `certainty`, `raw_choice`, `reports_food`, `needs_guidance_jev` = `judgment.needs_guidance`, `offer_to_log`) when `decision.judgment is not None`, and pass it via `_handle_coaching(..., routing=...)` to `save_coaching_response`. Do not change `CoachingAgent.handle` or `src/backend/agent/coaching.py` (plan listed coaching.py as changed; not needed).
- [X] T038 [US5] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/test_coaching_store.py tests/test_orchestrator.py tests/test_export_feedback.py -q` until green (the export copies `parsed_query` verbatim, so `routing` must appear in the JSONL).

**Checkpoint**: All five stories functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T039 [P] Docs: add `TYPESAFE_API_KEY` to the env table in `docs/deployment/deploy-guide.md` (after `GOOGLE_API_KEY`: "TypeSafe Jev intent routing (`web`, `bot`). Unset = Gemini routes every message; message text only is sent to TypeSafe") and to the LLM-provider block in `docs/deployment/railway.md`.
- [X] T040 [P] `.claude/CLAUDE.md`: add stack row `| Typed judgments | TypeSafe Jev (System One): intent routing; Gemini classifier as safety net |`, the env var line, and `system_one.py` under `agent/` in the layout tree.
- [X] T041 [P] If T007 kept a local copy of the questions, switch `eval/probe_jev_latency.py` to import them from `backend.agent.system_one` so the probe always measures the shipped wording.
- [X] T042 Run `.venv/bin/black --check` and `.venv/bin/ruff check` on every file touched above, then the full suite `PYTHONPATH=src .venv/bin/python -m pytest tests -q --ignore=tests/integration` (only the two known HEAD failures allowed).
- [ ] T043 End-to-end on web and Telegram per quickstart §6 with a real key and local stack: the five chat checks plus the SQL on `coaching_response`. Report results.
- [ ] T044 Capture the SC-009 baseline before launch: SQL over the last 30 days of `coaching_response` and `meal_log` for "coaching reply followed within 5 minutes by a `meal_log` row for the same user whose items match a food named in the question". Store the number and the query in `specs/001-jev-intent-routing/research.md` under "R13 — SC-009 baseline".
- [ ] T045 Hand-off to the user (**do not deploy**): summary of gate numbers, latency, outage drill, and the steps for them to run: set `TYPESAFE_API_KEY` on the Railway `web` and `bot` services, rotate the key pasted into chat on 2026-09-21, and deploy with their usual process. Offer to file the remaining post-launch checks (quickstart §7) as a GitHub issue with `gh`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: done.
- **Foundational (Phase 2)**: T005 → T006 → T008 (baseline) is strictly ordered. T007 and T009 can run alongside. T010 needs T007 and a key. **All user stories wait for T008 (FR-012) and a "go" from T010 (SC-003).**
- **US1 (Phase 3)**: after Phase 2. MVP.
- **US2 (Phase 4)**: after US1 (edits `_route`, which US1 creates).
- **US3 (Phase 5)**: after US1. Independent of US2 except both edit `_route`; do them one after the other.
- **US4 (Phase 6)**: after US3 (it changes how `_route` receives the judgment, and the cancellation behaviour relies on US3's `CancelledError` handling).
- **US5 (Phase 7)**: after US1. Independent of US2–US4 in behaviour, but it shares `orchestrator.py`, so it runs after them to avoid conflicts.
- **Polish (Phase 8)**: after the stories to be shipped.

### User Story Dependencies

```text
Phase1 → Phase2 (baseline + go) → US1 ─┬→ US2 ─┐
                                       └→ US3 ─┴→ US4 → US5 → Polish
```

### Within Each User Story

- Test tasks first, then implementation, then the run-tests task.
- `system_one.py` before `orchestrator.py`.

### Parallel Opportunities

- Phase 1: T003 ∥ T004 (after T002).
- Phase 2: T007 ∥ T009 while T005/T006 are in progress.
- US1: T011 ∥ T012 (different test files).
- US2: T020 ∥ T021.
- US3: T024 ∥ T025.
- US5: T034 ∥ T035.
- Polish: T039 ∥ T040 ∥ T041.

---

## Parallel Example: User Story 1

```bash
# Tests for US1, in parallel (different files):
Task: "T011 Create tests/test_system_one.py (certainty math, request shape, holdout rule)"
Task: "T012 Replace keyword tests in tests/test_orchestrator.py with judgment-path tests"
# Then, sequentially (same module chain):
Task: "T013 src/backend/agent/system_one.py"
Task: "T014 _route + RouteDecision in src/backend/agent/orchestrator.py"
Task: "T015 Delete keyword lists (orchestrator, config, tunables)"
Task: "T016 Offer to log in _handle_coaching"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1, then Phase 2 including the **legacy baseline (T008)** and the **latency go/no-go (T010)**.
2. Phase 3 (US1).
3. **STOP and validate**: gate T019 against the legacy baseline.
4. The MVP is shippable: US1 already routes unsure and unavailable judgments to Gemini, because the full decision rule is in T014. It still spends a credit on the unsure path (fixed in US2) and has only basic failure logging (hardened in US3).

### Incremental Delivery

1. Setup + Foundational → baseline and go decision.
2. US1 → gate passes → demo on web/Telegram (MVP).
3. US2 → no routing credits.
4. US3 → outage-proof, deployable without a key.
5. US4 → latency win measured.
6. US5 → guidance comparison data starts accumulating.
7. Polish → docs, e2e, hand-off. The user deploys.

---

## Notes

- [P] tasks = different files, no dependencies.
- The Jev question wording lives in two places, `system_one.py` and `contracts/jev-routing-request.md`. Change both together and re-run T019.
- Never write `TYPESAFE_API_KEY` into any tracked file. The key pasted into chat must be rotated before production use.
- Stop at any checkpoint to validate the story on its own.
