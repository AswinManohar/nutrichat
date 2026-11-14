# Mealsy — Observability

> Status: describes the code on branch `refactor/agent-structure`.
> Tracing backend: **Logfire** (Pydantic's OpenTelemetry platform), EU region.
> Project: `https://logfire-eu.pydantic.dev/aswinbio/starter-project`.
> The Logfire service name is still `nutrichat`.

This document explains how the backend is instrumented, what one chat turn
produces in the trace tree, how LLM cost is tracked, and what is and is not
exported. For the system architecture see [`architecture.md`](./architecture.md)
(§10 summarises this file). Span names are defined in
`src/backend/tracing.py`; setup is in `src/backend/observability.py`.

---

## 1. Why Logfire

Logfire is an OpenTelemetry (OTel) backend, so every layer of the stack emits
into one correlated trace tree:

- the HTTP request,
- the orchestrator's routing decision and the handler it picks,
- the LangGraph meal-logging nodes and the Pydantic AI coaching agent,
- every Gemini call (prompts, completions, token usage, dollar cost),
- GLiDE calls, USDA lookups, Postgres queries, Redis commands and Celery tasks.

One user message is one trace. A slow or expensive request shows, top to
bottom, where the time and the money went.

---

## 2. Configuration

All setup lives in `src/backend/observability.py`, as one idempotent function:

```python
configure_observability(app: FastAPI | None = None) -> None
```

| Process | Call site | `app` passed? |
|---|---|---|
| FastAPI API server | `main.py` (`configure_observability(app)`) | yes, enables FastAPI request spans |
| Celery worker | `workers/tasks.py`, `worker_process_init` handler | no |

A module-level `_configured` flag makes a second call a no-op, so importing the
app and the worker in one process (tests) never double-instruments.

### Environment variables

| Variable | Purpose |
|---|---|
| `LOGFIRE_TOKEN` | Write token that authorizes span ingestion. Lives in `.env`, never committed. |
| `LOGFIRE_ENVIRONMENT` | Environment tag on every span (`dev` by default; `production` on Railway). |
| `LOGFIRE_ENABLED` | Kill switch. Anything other than `true` ships no telemetry (see below). |

Without `LOGFIRE_TOKEN`, `send_to_logfire="if-token-present"` makes
configuration a local no-op: spans exist in memory but are never exported. That
is what lets tests, CI and a fresh clone run with no credentials.
`pyproject.toml` also sets `[tool.logfire] ignore_no_config = true`, so helpers
that call `logfire.info()` do not warn about missing configuration in tests.

> **Token gotcha.** Logfire has two credential types that look alike
> (`pylf_...`): a **write token** (Project settings, Write tokens), which
> `LOGFIRE_TOKEN` needs, and an **API key**, which is for the Query/Management
> API. An API key used as the write token returns `401 Invalid token`. The data
> region is read from the token, so no base URL is configured.

### The kill switch

`LOGFIRE_ENABLED=false` (set it in production to disable Logfire entirely)
configures Logfire with `send_to_logfire=False` and returns before any
instrumentor or the logging handler is attached. The `tracing.stage_span(...)`
calls in the code stay valid local no-ops.

### What `configure_observability` sets up

```python
logfire.configure(
    service_name="nutrichat",
    environment=os.environ.get("LOGFIRE_ENVIRONMENT", "dev"),
    send_to_logfire="if-token-present",
    scrubbing=logfire.ScrubbingOptions(callback=_scrub_extra),
)
```

Each instrumentor is wrapped in `try/except ImportError` with a
`logger.warning`, so a missing optional dependency degrades instead of
crashing startup.

| Instrumentation | Call | What it captures |
|---|---|---|
| **Logging handler** | `LogfireLoggingHandler(level=INFO)` on the `backend` logger | Stdlib `logger.info/warning/error` lines from `backend.*`, shown under the span that was open when they were written. Only the `backend` logger: the root logger also carries third-party libraries, whose volume would swamp the trace. A `backend` logger with no level of its own is set to INFO. |
| **FastAPI** | `logfire.instrument_fastapi(app)` | Route, method, status, latency; the root span of each request tree. API process only. |
| **Pydantic AI** | `logfire.instrument_pydantic_ai(version=3)` | `invoke_agent <name>` spans for the coaching, parse, meal-suggestion and USDA-estimate agents, with `chat <model>` children, token usage and tool calls. Version 3 is what Logfire's Agents view reads (the default, 2, emits `agent run`). |
| **LangChain / LangGraph** | `LangchainInstrumentor().instrument()` (OpenLLMetry) | Every LangGraph node run and every `ChatGoogleGenerativeAI` call: prompts, completions, model, token usage. |
| **httpx** | `logfire.instrument_httpx(capture_all=True)` | Raw HTTP to Gemini for Pydantic AI (its `GoogleModel` uses httpx) and to GLiDE. Request and response bodies and headers; secret headers are redacted (see §8). |
| **aiohttp** | `logfire.instrument_aiohttp_client()` | USDA FoodData Central calls (URL, status, latency). |
| **asyncpg** | `logfire.instrument_asyncpg()` | Every Postgres statement and its latency, including checkpoint reads and writes. |
| **Redis** | `logfire.instrument_redis()` | Redis commands (today's totals, coaching history, rate limits, Celery broker). |
| **Celery** | `logfire.instrument_celery()` | Task enqueue and task execution spans. |

### Pydantic AI specifics

`instrument_pydantic_ai()` sets a class-level default that is read when
`.run()` is called, not when an agent is built. The coaching agents are
constructed at import time, before `configure_observability()` runs, and are
still traced for that reason.

---

## 3. Span naming

Defined in `src/backend/tracing.py`, which is the one place to grep for a span:

- A span is named `<area>.<step>` after the package it lives in under
  `agent/`: `routing`, `meal_logging`, `food`, `coaching`, `memory`, plus
  `safety` and `glide`. The root span of a chat turn is plain `turn`.
- Call sites open spans with `tracing.stage_span(NAME, **attributes)`, never
  `logfire.span` directly.
- Attributes are ids, counts (`n_*`), enums and timings (`*_ms`). Never the
  user's message, a reply, a food's free text or image data.
- Two names are fixed by their consumers: `invoke_agent meal_logging` (Logfire's
  Agents view reads that exact name and its `gen_ai.*` attributes) and
  `memory.apply_ops`.
- Telegram handlers still open their own `telegram_update` spans.

Helpers in `tracing.py`:

| Helper | Use |
|---|---|
| `stage_span(name, **attrs)` | Open a stage span. |
| `record_handled(exc, stage=...)` | Mark a failure that was caught and replaced by a fallback (see §7). |
| `set_current_attribute(key, value)` | Set an attribute on whichever span is open, for code that runs inside a span it does not own (the coaching `branch`). No-op when nothing is recording. |

---

## 4. The trace tree of one chat turn

A turn takes one of four paths: red-flag reply, readback answer, coaching or
meal logging. Only one of the branches below runs. The tree below
combines the branches; arrows mark where they differ:

```
POST /meals/log
└─ turn
   ├─ safety.red_flag_screen
   ├─ glide.ask (purpose=routing)           ← started as a task, see below
   ├─ routing.decide
   │  └─ routing.second_opinion             ← only when GLiDE is unsure or unavailable
   ├─ invoke_agent meal_logging             ← meal-logging path
   │  ├─ LangGraph node spans (auto)
   │  ├─ food.lookup_batch
   │  │  └─ food.resolve                    ← one per entity, run concurrently
   │  └─ meal_logging.card_check
   ├─ coaching.turn                         ← coaching path
   │  ├─ coaching.context                   ← these two start together with the
   │  ├─ memory.extract_turn                ←  parse_query run (asyncio.gather)
   │  │  └─ glide.ask (purpose=memory_judge)
   │  ├─ coaching.fetch_data                ← these two start together, after
   │  ├─ coaching.retrieve                  ←  the first group
   │  ├─ coaching.suggest_meal              ← recipe turns
   │  │  └─ coaching.check_recipe           ← one per attempt
   │  └─ invoke_agent coaching              ← prose turns (Pydantic AI)
   │     └─ coaching.reply_guard            ← output validator, once per attempt
   │        └─ glide.ask (purpose=reply_guard)
   └─ memory.readback_reply                 ← readback path
```

Where the real nesting differs from a flat reading of that tree:

- **`glide.ask (purpose=routing)` is a child of `turn`, not of
  `routing.decide`.** The orchestrator starts `judge_message` as an
  `asyncio` task before `routing.decide` opens, so it overlaps the checkpoint
  read, and the task keeps the context it was created in. `routing.decide` then
  awaits that task. The GLiDE call therefore appears as a sibling that starts
  earlier and usually ends before `routing.decide`.
- **The branches are alternatives.** `routing.decide` is absent when a paused
  meal card resumes, when an image is attached, when a readback answer takes
  the message and when the red-flag screen replies (the turn then ends after
  `safety.red_flag_screen` with `intent=safety`). `coaching.turn` and
  `invoke_agent meal_logging` never appear in the same turn.
- **`coaching.turn` opens after the credit check.** An over-quota user gets the
  upgrade message with no `coaching.turn` span.
- **`coaching.reply_guard` sits under the Pydantic AI agent span**, not directly
  under `coaching.turn`, because the guard runs as the agent's output
  validator. It runs once per attempt, so a rewritten reply shows it twice.
- **`coaching.suggest_meal` also holds `invoke_agent meal_suggestion`** (the
  Pydantic AI recipe call) next to each `coaching.check_recipe`.
- **Coaching stages overlap.** `coaching.context`, `memory.extract_turn` and
  the `parse_query` agent run start together in one `asyncio.gather`;
  `coaching.fetch_data` and `coaching.retrieve` start together afterwards.
  Siblings are ordered by start time, so read durations, not position.
- **`memory.extract_turn` is called from three places.** Inside `coaching.turn`
  (as drawn); directly under `turn` when a "no, it's ..." reply is read as a
  readback correction; and under `memory.curate_turn` in the worker.
- **`meal_logging.card_check` is not only under the agent span.** After a
  readback answer on a paused card it is a child of `turn`
  (the card is rebuilt in the orchestrator), and `GET /meals/pending` opens it
  under the request span, with no `turn`.
- **`glide.ask (purpose=warm_up)`** runs once at startup, outside any turn, as
  a root span.
- **Spans that never nest under `turn`:** `meal_logging.resolve_ingredient`
  (the "replace ingredient" endpoint in `api/my_meals.py`).
- **Side effects after the reply** (`_record_turn`, the Celery enqueue) run
  after `turn` closes, under the request span.

### 4.1 Cost and the tree

`llm_cost` records are log points nested under whichever span was active when
the call finished (see §9). The Pydantic AI runs and LangChain calls inside the
branches above each leave one.

### 4.2 Worker-side spans

The worker is its own process and its own trace, linked to the request by the
Celery enqueue span. `instrument_celery()` gives each task an execution span;
the stage spans below hang under it.

| Task | Stage spans |
|---|---|
| `extract_and_store_facts` | `memory.curate_turn`, containing `memory.extract_turn` (and its `glide.ask (memory_judge)`) and `memory.apply_ops` |
| `infer_log_habits` (weekly, one per eligible user) | `memory.infer_log_habits`, containing `memory.apply_ops` |
| `embed_meal_summary`, the cron summaries, `notify_escalation`, push tasks | Celery task span only |

---

## 5. Span reference

"Opened in" is `file:function` under `src/backend/`. Attribute values come from
the code.

| Span | Opened in | Attributes |
|---|---|---|
| `turn` | `agent/orchestrator.py:handle_message` | `user_id`, `thread_id`, `has_image` at open. `intent` at close: `safety`, `readback`, `coaching` or `log_meal`. `paused` (bool) at close, absent on the `safety` path. |
| `safety.red_flag_screen` | `agent/orchestrator.py:_screen_red_flags` | `rule_id` (the matched rule, `none`, or `unavailable` when the rule file cannot be read), `duration_ms`. Never the text. |
| `routing.decide` | `agent/routing/router.py:route_message` | `path` (`judgment`, `second_opinion_unsure`, `second_opinion_unavailable`), `intent` (`log_meal`, `coaching`), `offer_to_log` (bool), `failure` when GLiDE gave no answer (`not_requested`, `not_configured`, `timeout`, `http_<status>`, `malformed_response`, or an httpx exception class name). When GLiDE answered: `certainty`, `raw_choice`, `reports_food`, `needs_guidance_jev`, `judgment_ms`, `judge_model`, `judgment_input_tokens`. |
| `routing.second_opinion` | `agent/routing/router.py:_classify_with_gemini` | none |
| `glide.ask` | `agent/glide.py:ask` | `purpose` (`routing`, `warm_up`, `memory_judge`, `reply_guard`), `model`, `outcome` (`ok` or the failure reason as above), `input_tokens` on success. A failure is an outcome, not a span error. |
| `invoke_agent meal_logging` | `agent/meal_logging/handler.py:handle_meal_logging` | `gen_ai.operation.name`, `gen_ai.agent.name`, `gen_ai.conversation.id` (thread id), `gen_ai.request.model`, `gen_ai.input.messages`, `gen_ai.output.messages`. The two message attributes carry the user's text and the reply (see §8). |
| `food.lookup_batch` | `agent/food/usda.py:usda_lookup_batch` | `n_entities`, `n_estimated`, `n_miss` |
| `food.resolve` | `agent/food/usda.py:_fetch_one` | `source` (`local`, `fdc_api`, `llm_estimate`, `miss`), `match_confidence`, `fdc_id`, `fell_back` (bool). Never the food name. |
| `meal_logging.card_check` | `agent/meal_logging/card.py:card_fields` | `n_warnings` |
| `meal_logging.resolve_ingredient` | `agent/meal_logging/replace_ingredient.py:resolve_ingredient` | `mode` (`swap`, `add`), `text_len`, `n_foods`, `amount_stated`, `source`, `estimated`, `latency_ms` |
| `coaching.turn` | `agent/coaching/handler.py:handle_coaching` | `branch` (`withheld`, `recipe`, `no_data`, `answer`), `needs_guidance`, `retrieved_count`, `citation_count`, `response_id`, `profile_unavailable` (only when set) |
| `coaching.context` | `agent/coaching/agent.py:_context_prompt` | `fallback` (`none`, `restrictions_only`) |
| `coaching.fetch_data` | `agent/coaching/agent.py:fetch_data` | `time_range` (the parsed range, for example `today`, `this_week`), `source` (`redis`, `postgres`), `n_micronutrients` |
| `coaching.retrieve` | `agent/coaching/agent.py:_retrieve_passages` | `n_passages` |
| `coaching.suggest_meal` | `agent/coaching/suggest.py:suggest_meal` | `attempts`, `shown` (bool), `unavailable` (exception class name, when the safety tables or food DB could not be read) |
| `coaching.check_recipe` | `agent/coaching/suggest.py:_suggest` | `attempt`, `passed` (bool), `failed_rules` (comma-separated rule names) |
| `coaching.reply_guard` | `agent/coaching/reply_judge.py:guard` | `layer` (`lexical`, `usda`, `glide`, `none`), `layer_skipped` (`glide`, when GLiDE gave no answer), `glide_probability` |
| `memory.extract_turn` | `agent/memory/curator.py:extract_turn` | `n_proposed`, `n_kept` |
| `memory.curate_turn` | `agent/memory/curator.py:curate_turn` | `n_applied` |
| `memory.infer_log_habits` | `agent/memory/curator.py:infer_log_habits` | `n_proposed`, `n_kept`, `n_applied` |
| `memory.apply_ops` | `agent/memory/facts.py:apply_ops` | `actor` (`user`, `curator`, `weekly`), `n_ops`, `n_applied`, `n_evicted` |
| `memory.readback_reply` | `agent/orchestrator.py:_answer_readback` | `answer` (`confirm`, `reject`, `correction`) |

Spans written by instrumentors rather than by hand are not listed:
`invoke_agent coaching`, `coaching_parse`, `meal_suggestion`, `usda_estimate`
(Pydantic AI), `chat <model>`, LangGraph node spans, and the HTTP, SQL, Redis
and Celery spans.

---

## 6. Telegram

The handlers in `telegram/handlers.py` open their own `telegram_update` spans
(with `chat_id` and `kind`) via `logfire.span`. They call `handle_message` in-process,
so the turn tree above hangs under them.

---

## 7. Handled failures

Some failures are caught and replaced by a fallback, so the turn goes on. For
these, `tracing.record_handled(exc, stage=...)` adds an `exception` event
carrying `exception.type` only, and sets `handled_error=<stage>` on the span
that is open when it runs. The span is not marked failed. The exception's
message and traceback are left out because a validation error can echo the
user's text.

| `handled_error` | Where | Fallback |
|---|---|---|
| `extract_entities` | `meal_logging/graph.py` | no entities |
| `decompose` | `meal_logging/decompose.py` | the dish stays one item |
| `find_saved_meal` | `meal_logging/saved_meals.py` | no saved-meal match |
| `log_reply` | `meal_logging/meals.py` | canned logged-meal reply |
| `estimate_nutrition` | `food/usda.py` | the food is reported as a miss |
| `build_context` | `coaching/agent.py` | coach with restrictions only |
| `record_turn` | `orchestrator.py` | the exchange is not added to coaching history |

The attribute lands on the innermost open span: a graph node's failure is on
the `invoke_agent meal_logging` subtree, `estimate_nutrition` on
`food.resolve`, `build_context` on `coaching.context`. `record_turn` runs
after `turn` closes, so it lands on the request span.

To find them in Logfire:

```sql
SELECT start_timestamp, span_name, attributes->>'handled_error' AS stage
FROM records WHERE attributes->>'handled_error' IS NOT NULL
ORDER BY start_timestamp DESC;
```

---

## 8. Privacy and scrubbing

What is exported:

- **Stage spans never carry user text.** The attributes in §5 are ids, counts,
  enums and timings. The red-flag screen in particular must not leak message
  text through a span (spec 013, FR-015).
- **Prompts and completions are captured, by design.** The LangChain
  instrumentor records every Gemini prompt and completion on the meal-logging
  and memory paths, the Pydantic AI instrumentation records the coaching
  agents' messages, `instrument_httpx(capture_all=True)` records request and
  response bodies, and `invoke_agent meal_logging` carries the user message and
  reply as `gen_ai.*.messages`. A user's message therefore reaches Logfire
  through those, not through stage spans. Treat the Logfire project as
  holding user content.
- **The logging handler exports log arguments.** Records from the `backend`
  logger are exported with their formatted message and arguments. A log line
  must never format user text (a message, a food name, a reply). Log ids,
  counts and exception type names, as the existing lines do.

Two scrubbing layers run on every exported span:

1. **Logfire default scrubbing** redacts values whose attribute names match
   built-in secret patterns (`authorization`, `api_key`, `x-goog-api-key`,
   `token`, `password`, `secret`, ...). This is what makes `capture_all=True`
   on httpx safe for the Gemini API-key header.
2. **Image scrubber**: `_scrub_extra()` in `observability.py`, passed as
   `ScrubbingOptions(callback=...)`, replaces with `"<redacted image>"`:
   - any attribute whose key path contains `image_b64`,
   - any string matching a `data:image/...;base64,` URI,
   - any base64-looking blob of 1024 characters or more.

`image_b64` and the LangGraph checkpointer object are also never passed to a
span as attributes.

---

## 9. Cost tracking

Module: `src/backend/agent/cost.py`. Token usage is on every LLM span already;
cost tracking turns it into dollars with
[`genai-prices`](https://github.com/pydantic/genai-prices), an offline price
table (no network call, no added latency). Both paths end in the same
`_emit_cost`, which emits two signals:

| Signal | Name | Use |
|---|---|---|
| Log point, nested under the active span | `llm_cost` | Per-call drill-down. Fields: `operation`, `model`, `priced_as`, `input_tokens`, `output_tokens`, `input_usd`, `output_usd`, `cost_usd`. |
| Metric counter | `gen_ai.cost_usd` (unit USD) | Aggregate spend over time, labelled by `model` (the matched price-table id) and `operation`. |

### The two paths

- **Pydantic AI runs** call `record_run_cost(result, model, operation=...)` after
  the run, which prices `result.usage`.
- **LangChain calls** are priced by `LlmCostCallback`, a callback that
  `make_llm(operation=...)` attaches to the model. It reads `usage_metadata`
  from the response (including cached input tokens). Because the model's own
  callbacks fire whatever chain wraps it, it also covers
  `.with_structured_output(...)` and calls made in a worker thread. A
  `make_llm()` call without `operation` is not priced.

### `operation` values

| Path | Operation |
|---|---|
| Pydantic AI | `parse_query`, `coaching_response`, `suggest_meal`, `estimate_nutrition` |
| LangChain: meal logging | `extract_entities`, `classify_food_image`, `apply_correction`, `log_reply`, `decompose`, `replace_ingredient` |
| LangChain: routing | `intent_second_opinion` |
| LangChain: memory | `memory_curator`, `memory_log_habits` |

Not priced: GLiDE (a separate provider, not Gemini; its input tokens are on
`glide.ask`), embeddings (`gemini-embedding-001` is not in the price table), and
the offline `scripts/backfill_memory_profile.py`. A model missing from the
price table is skipped without raising; cost tracking must never break a
request.

### Spend queries

In Logfire, chart `gen_ai.cost_usd` grouped by `operation` or `model`, or query
the records:

```sql
-- spend today, by operation
SELECT attributes->>'operation' AS op, sum((attributes->>'cost_usd')::float) AS usd
FROM records
WHERE message = 'llm_cost' AND start_timestamp > now() - interval '1 day'
GROUP BY op ORDER BY usd DESC;
```

---

## 10. Runbook

**Start the stack with tracing on** (the code does not load `.env` itself):

```bash
PYTHONPATH=src uv run --env-file .env uvicorn backend.main:app \
    --host 127.0.0.1 --port 8000
PYTHONPATH=src uv run --env-file .env celery -A backend.workers.tasks \
    worker --loglevel=info
```

A local backend with the repository `.env` writes to the production database
and, with `LOGFIRE_TOKEN` set, exports to the Logfire project that token belongs
to. Leave
`LOGFIRE_TOKEN` unset for local work that does not need traces.

**Verify ingestion.** Healthy startup logs contain no `401` or `Failed to
export` lines:

```bash
uv run --env-file .env uvicorn backend.main:app --app-dir src 2>&1 \
    | grep -iE "401|failed to export|invalid token"
```

**Run without tracing** (tests, offline dev): leave `LOGFIRE_TOKEN` unset, or
set `LOGFIRE_ENABLED=false`.

**Find one turn.** Every `coaching_response` row stores the `trace_id` of its
turn (`agent/coaching/handler.py`), so a rated or reported coaching reply can be
opened directly in Logfire.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401 Invalid token` | An API key was used as `LOGFIRE_TOKEN`. | Use a write token (Project settings, Write tokens). |
| Spans exist locally but not in Logfire | `LOGFIRE_TOKEN` unset (no-op mode), or `LOGFIRE_ENABLED=false`. | Set the write token, enable Logfire, restart. |
| `LogfireNotConfiguredWarning` in tests | A helper ran before configuration. | Already suppressed by `[tool.logfire] ignore_no_config`. |
| No Gemini HTTP span for coaching | httpx instrumentor missing. | Check startup logs for `logfire httpx instrumentation unavailable`. |
| No `llm_cost` for a call | Model not in the price table, no `usage_metadata`, or `make_llm()` called without `operation`. | Pass `operation=`; for a new model check `genai-prices`. |
| A saved Logfire query or dashboard filtering on an old span name shows nothing | Span names changed (see §11). | Update the filter to the new name. |
| Backend log lines missing under a span | Logging handler is attached only to the `backend` logger at INFO and above, and not when `LOGFIRE_ENABLED=false`. | Log from a `backend.*` logger at INFO or higher. |

---

## 11. Span names that changed

Saved Logfire queries, dashboards and alerts that filter on an old name need
updating.

| Old name | New name |
|---|---|
| `handle_message` | `turn` |
| `route_message` | `routing.decide` |
| `classify_intent_llm` | `routing.second_opinion` |
| `coaching` | `coaching.turn` |
| `red_flag_screen` | `safety.red_flag_screen` |
| `readback_reply` | `memory.readback_reply` |
| `suggest_meal` | `coaching.suggest_meal` |
| `check_recipe` | `coaching.check_recipe` |
| `reply_guard` | `coaching.reply_guard` |
| `resolve_ingredient` | `meal_logging.resolve_ingredient` |

Unchanged: `invoke_agent meal_logging`, `memory.apply_ops`, the `llm_cost`
record, the `gen_ai.cost_usd` metric and the Telegram spans.

---

## 12. File map

| File | Role |
|---|---|
| `src/backend/observability.py` | `configure_observability()`, the instrumentors, the logging handler, the image scrubber. |
| `src/backend/tracing.py` | Span names, `stage_span`, `record_handled`, `set_current_attribute`. |
| `src/backend/agent/cost.py` | `record_run_cost`, `LlmCostCallback`, pricing, the `llm_cost` record and `gen_ai.cost_usd` metric. |
| `src/backend/agent/llm.py` | `make_llm(operation=...)` attaches the cost callback. |
| `src/backend/agent/orchestrator.py` | `turn`, `safety.red_flag_screen`, `memory.readback_reply`. |
| `src/backend/main.py` | `configure_observability(app)` for the API process. |
| `src/backend/workers/tasks.py` | `worker_process_init` calls `configure_observability()` for each worker. |
| `tests/test_tracing.py` | Asserts the trace shape, the cost records and that no span carries user text. |
| `pyproject.toml` | `[tool.logfire] ignore_no_config = true`. |
