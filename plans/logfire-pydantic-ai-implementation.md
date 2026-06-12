# Implementation Plan: Logfire Observability + Pydantic AI Coaching Pilot

**Status: APPROVED — execute fully, including commits. Plan mode is NOT active.**
Repo: `/home/aswinmanohar/nutrichat`. Run everything with `uv run` from the repo root.
Follow `.claude/CLAUDE.md` standards: black (88 chars), ruff, Google docstrings, full type
annotations, `from __future__ import annotations`, async I/O, Pydantic for boundary data.

## Goal

1. Replace LangSmith tracing (wired in commit `70316e6`) with **Logfire** (OpenTelemetry).
2. Port the **coaching agent** (`src/backend/agent/coaching.py`) from LangChain to
   **Pydantic AI** as an isolated pilot. Do NOT touch the LangGraph meal-logging flow.

## Current state you are modifying

- `src/backend/agent/orchestrator.py` — has `from langsmith import traceable`,
  a `_trace_inputs()` helper, and `@traceable(...)` decorators on `_classify_intent`,
  `handle_message`, `_handle_meal_logging`, `_handle_coaching`. Remove all of these.
- `src/backend/agent/coaching.py` — current pipeline:
  - `QueryParsed(BaseModel)`: `time_range: Literal["today","yesterday","this_week","last_7_days","custom"]`,
    `date_from/date_to: date | None`, `nutrients: list[str]`, `include_goals: bool`, `extra="forbid"`.
  - `parse_query()` → `_query_parser_llm.ainvoke(...)` (LangChain flash-lite structured output).
  - `_resolve_date_range()`, `fetch_data()` — pure Python + DB/Redis. **Keep byte-identical.**
  - `generate_response()` → `make_llm(COACHING_MODEL).ainvoke(...)`.
  - `CoachingAgent.handle()` — orchestrates, returns graceful strings
    ("No meals logged for that period yet." / "I don't have data on X for that period.").
- Prompts come from `backend.config.get_tunables().prompts` (`query_parse_system`,
  `coaching_response_system`). Model names from `backend.agent.llm`
  (`FLASH_LITE_MODEL`, `COACHING_MODEL`). Reuse these; hardcode nothing.
- `.env` has `LANGSMITH_TRACING=true` + key; `GOOGLE_API_KEY` is set.
- `src/backend/main.py` — FastAPI app, lifespan sets up AsyncPostgresSaver, CORS middleware.
- `src/backend/workers/tasks.py` — Celery app `celery_app`, async bodies wrapped by `_run()`.
- Tests: `tests/test_coaching.py` (8 tests, patches `backend.agent.coaching._query_parser_llm`
  and `generate_response`), `tests/test_orchestrator.py` (8 tests, patches
  `_classify_intent`, `_coaching_agent.handle`, `extract_and_store_facts`). 83 unit tests total pass today.

## Step 1 — Dependencies

Verify exact names on PyPI before adding (use `uv add` and check resolution):

```bash
uv add "logfire[fastapi,asyncpg,redis,celery,httpx]" "pydantic-ai-slim[google]"
uv add opentelemetry-instrumentation-langchain opentelemetry-instrumentation-aiohttp-client
```

Notes:
- `opentelemetry-instrumentation-langchain` is the OpenLLMetry (Traceloop) instrumentor;
  if unresolvable, fall back to `openinference-instrumentation-langchain` and adapt step 3.
- If a logfire extra doesn't exist, install the matching
  `opentelemetry-instrumentation-<lib>` package directly.

## Step 2 — Env files

- `.env`: set `LANGSMITH_TRACING=false` (keep the key line as-is). Add:
  `LOGFIRE_TOKEN=` (empty — user fills later) and `LOGFIRE_ENVIRONMENT=dev`.
- `.env.example`: same two new vars with one-line comments
  (`# logfire.pydantic.dev -> project -> Write tokens`).

## Step 3 — New module `src/backend/observability.py`

```python
"""Logfire/OpenTelemetry setup. Call configure_observability() once per process."""
```

- `_scrub(m: logfire.ScrubMatch)` -> redact; plus a custom scrubbing callback approach:
  implement `configure_observability(app: FastAPI | None = None) -> None`:
  1. `logfire.configure(service_name="nutrichat", environment=os.environ.get("LOGFIRE_ENVIRONMENT", "dev"), send_to_logfire="if-token-present", scrubbing=logfire.ScrubbingOptions(callback=_scrub_extra))`
     — `send_to_logfire="if-token-present"` makes everything a no-op without a token
     (tests/CI safe). Check the installed logfire version's actual API with
     `uv run python -c "import logfire; help(logfire.configure)"` and adapt arg names.
  2. `_scrub_extra` must redact: any attribute whose key contains `image_b64`, and any
     string value that looks like a base64 blob > 1KB (regex `^[A-Za-z0-9+/=\s]{1024,}$`)
     or a `data:image/...;base64,` URI → replace with `"<redacted image>"`.
  3. Instrument (guard each in try/except ImportError with a logger.warning):
     - `logfire.instrument_fastapi(app)` when `app` is given
     - `logfire.instrument_asyncpg()`
     - `logfire.instrument_redis()`
     - `logfire.instrument_celery()` (call in worker context; safe to call always)
     - `logfire.instrument_aiohttp_client()` if available, else
       `AioHttpClientInstrumentor().instrument()` from
       `opentelemetry.instrumentation.aiohttp_client`
     - LangChain/LangGraph: `from opentelemetry.instrumentation.langchain import LangchainInstrumentor; LangchainInstrumentor().instrument()`
  4. Idempotency guard: module-level `_configured` flag so a second call is a no-op.
- `__all__ = ["configure_observability"]`.

## Step 4 — Wire it in

- `src/backend/main.py`: in the lifespan function (before yield) or right after `app`
  creation, `from backend.observability import configure_observability;
  configure_observability(app)`. Import at top of file per style.
- `src/backend/workers/tasks.py`: add
  ```python
  from celery.signals import worker_process_init

  @worker_process_init.connect
  def _init_observability(**_: object) -> None:
      """Configure Logfire in each Celery worker process."""
      configure_observability()
  ```

## Step 5 — Orchestrator spans (replace LangSmith)

In `src/backend/agent/orchestrator.py`:
- Delete `from langsmith import traceable`, `_trace_inputs()`, and all 4 `@traceable` decorators.
- Add `import logfire`.
- In `handle_message`, wrap the body:
  ```python
  with logfire.span(
      "handle_message", user_id=user_id, thread_id=thread_id, has_image=bool(image_b64)
  ) as span:
      ...existing logic...
      span.set_attribute("intent", "coaching" if <coaching path> else "log_meal")
      span.set_attribute("paused", result["paused"])
  ```
- `_classify_intent`: wrap LLM-fallback branch in `logfire.span("classify_intent_llm")`
  (the keyword path needs no span). `_handle_coaching` and `_handle_meal_logging` each get
  a `with logfire.span("coaching")` / `with logfire.span("meal_logging")` around their body
  (or `@logfire.instrument(...)` decorators — but ensure tests that patch these module
  attributes still pass; plain `with` blocks inside the functions are safest).
- NEVER pass `image_b64` content or `checkpointer` as span attributes.

## Step 6 — Pydantic AI coaching pilot

Rewrite ONLY the LLM plumbing in `src/backend/agent/coaching.py`:

```python
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
```

- Module level (keep names so other imports don't break):
  ```python
  _parse_agent = Agent(
      GoogleModel(FLASH_LITE_MODEL),
      output_type=QueryParsed,
      system_prompt=_TUNABLES.prompts.query_parse_system,
  )
  _response_agent = Agent(
      GoogleModel(COACHING_MODEL),
      system_prompt=_TUNABLES.prompts.coaching_response_system,
  )
  ```
  - GoogleModel reads `GOOGLE_API_KEY` from env by default via GoogleProvider — verify with
    the installed pydantic-ai version; if it wants `GEMINI_API_KEY`, construct
    `GoogleProvider(api_key=os.environ.get("GOOGLE_API_KEY", ""))` explicitly.
  - Gemini model-name format: pydantic-ai expects bare names like
    `gemini-2.5-flash` (no `models/` prefix) — FLASH_LITE_MODEL/COACHING_MODEL are
    already bare; pass through.
- `parse_query(message)` → `result = await _parse_agent.run(message); return result.output`.
- `generate_response(message, data)` → build the same user content string
  (`User question: ...\n\nData:\n{json.dumps(data, default=str)}`) →
  `result = await _response_agent.run(content); return result.output`.
- `QueryParsed`: pydantic-ai structured output with Gemini may reject `extra="forbid"`
  or Optional dates — if schema errors occur, relax to `extra="ignore"` and note it.
- Keep `fetch_data`, `_resolve_date_range`, `CoachingAgent.handle`, `_MACRO_ALIASES`,
  graceful messages, and `__all__` unchanged.
- Add `logfire.instrument_pydantic_ai()` to `observability.py` step 3 instrumentations
  (or `Agent.instrument_all()` — check installed API).
- Remove now-unused LangChain imports from coaching.py.

## Step 7 — Rewrite `tests/test_coaching.py` LLM mocking

Use pydantic-ai's test utilities (no network):

```python
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.function import FunctionModel

# parse_query test:
with coaching._parse_agent.override(model=TestModel(custom_output_args={...})):
    parsed = await coaching.parse_query("how much protein today?")
```

- For exact `QueryParsed` outputs use `TestModel(custom_output_args={"time_range": "today", ...})`
  or `FunctionModel` returning the structured payload. Verify the exact kwarg name
  (`custom_output_args`) against the installed version (`uv run python -c "from pydantic_ai.models.test import TestModel; help(TestModel)"`).
- `generate_response` tests: override `_response_agent` with `TestModel(custom_output_text="...")`.
- Keep the `fetch_data` tests (mock session/redis) unchanged — they don't touch LLMs.
- `CoachingAgent.handle` tests currently patch `backend.agent.coaching.parse_query` /
  `generate_response` / `fetch_data` as module attributes — those patches still work; keep them.
- `tests/test_orchestrator.py` should pass unmodified (it patches `_coaching_agent.handle`).
  If importing orchestrator now pulls pydantic_ai at import time and anything breaks, fix imports.

## Step 8 — Docs

- `docs/architecture.md`: §1 diagram label "LangSmith" → "Logfire"; §6/§7 mention the
  observability module; add one paragraph: what is traced (FastAPI, orchestrator spans,
  LangGraph nodes + Gemini calls via OTel instrumentor, USDA aiohttp, asyncpg, redis,
  celery, pydantic-ai coaching), and the image-b64 scrubbing rule.
- `.claude/CLAUDE.md` tech-stack table: `| Agent | LangGraph, Langsmith · ...` →
  `| Agent | LangGraph (logging) · Pydantic AI (coaching pilot) · tool-use router pattern |`
  and add a row `| Observability | Logfire (OpenTelemetry) |`.

## Acceptance criteria (all must pass before committing)

1. `uv run pytest tests/ -m "not integration"` — fully green.
2. `uv run black src/backend --check` and `uv run ruff check src/backend` — clean
   (run `uv run black src/backend` + `--fix` first as needed).
3. Without LOGFIRE_TOKEN:
   `uv run python -c "import sys; sys.path.insert(0,'src'); from backend.main import app; from backend.workers.tasks import celery_app; print('ok')"`.
4. `grep -rn "langsmith" src/backend` returns nothing (package may stay in lockfile as a
   transitive langgraph dep — that's fine).
5. One git commit, message `feat: Logfire observability + Pydantic AI coaching pilot`
   with body summarizing changes, trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
   Stage only: `src/backend`, `tests`, `docs/architecture.md`, `.claude/CLAUDE.md`,
   `.env.example`, `pyproject.toml`, `uv.lock`, `plans/logfire-pydantic-ai-implementation.md`.
   Do NOT stage `.env`. Do NOT push.

## Explicitly out of scope

- No changes to `agent/graph.py`, `agent/tools/*`, frontend, eval, Telegram.
- No live service restarts or Logfire-dashboard verification (main thread does this
  once the user's LOGFIRE_TOKEN exists).
- No migration of the meal-logging graph to Pydantic AI.

## Report back

What changed per file, test/lint results, any API-name deviations you had to make
(package names, GoogleModel/provider args, TestModel kwargs), and what still needs
the LOGFIRE_TOKEN to verify.
