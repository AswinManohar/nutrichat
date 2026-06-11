# NutriChat — System Architecture

> Status: reflects the implemented backend as of 2026-06-11 (milestones M0–M5
> complete; web frontend, Telegram bot, and eval harness not yet built).
> Diagrams are Mermaid — rendered by GitHub, VS Code (with the Mermaid
> extension), or https://mermaid.live.

## 1. System overview

```mermaid
flowchart TB
    subgraph Clients
        WEB["Web app (React 19)\n— planned M6"]
        TG["Telegram bot (aiogram)\n— planned M7"]
        CURL["curl / API clients\n(current test interface)"]
    end

    subgraph FastAPI["FastAPI backend (src/backend)"]
        AUTH["auth/supabase.py\nJWT validation\n(DEV_BYPASS_AUTH escape hatch)"]
        MEALS_API["api/meals.py\nPOST /meals/log"]
        GOALS_API["api/goals.py\nGET/POST/PUT /goals"]
        ORCH["agent/orchestrator.py\nhandle_message()\nintent routing"]
    end

    subgraph Agents
        GRAPH["agent/graph.py\nLangGraph meal-logging graph\n(interrupt-based confirmation)"]
        COACH["agent/coaching.py\nCoachingAgent\nparse → fetch → respond"]
    end

    subgraph Tools
        MEALS_T["tools/meals.py\nextract · correct · log"]
        USDA_T["tools/usda.py\ncache-first FDC lookup"]
        HIST_T["tools/history.py\nmacro/micro ranges + ANN"]
        CTX["agent/context.py\nbuild_context / system prompt"]
    end

    subgraph Workers["Celery (workers/tasks.py)"]
        EMBED["embed_meal_summary\n(on every log)"]
        FACTS["extract_and_store_facts\n(not yet enqueued — see review)"]
        DAILY["aggregate_daily_summary\n(cron 00:05)"]
        WEEKLY["build_weekly_summary\n(cron Sun 23:00)"]
        RESET["reset_day_keys\n(cron 00:00)"]
    end

    subgraph Storage
        PG[("PostgreSQL 16 + pgvector\nmeal_log · user_goal · user_memory\nfood_source · daily_summary\nweekly_summary · checkpoints")]
        RDS[("Redis\ntoday:{user} totals\n+ Celery broker")]
    end

    subgraph External
        GEM["Gemini API\nflash-lite (extraction/intent)\n2.5-flash (coaching)\ngemini-embedding-001"]
        FDC["USDA FoodData Central"]
        SUPA["Supabase Auth"]
    end

    CFG["config/tunables.yaml\nprompts · models · thresholds"]

    WEB & TG & CURL --> AUTH --> MEALS_API
    AUTH --> GOALS_API
    MEALS_API --> ORCH
    ORCH -->|log_meal / paused / image| GRAPH
    ORCH -->|coaching question| COACH
    GRAPH --> MEALS_T --> USDA_T
    COACH --> HIST_T
    COACH --> CTX
    MEALS_T -->|".delay()"| EMBED
    USDA_T --> FDC
    USDA_T <--> PG
    MEALS_T --> PG
    MEALS_T --> RDS
    HIST_T --> PG
    CTX --> PG
    CTX --> RDS
    GRAPH <-->|checkpoints| PG
    Workers --> PG
    Workers --> RDS
    MEALS_T & COACH & ORCH & EMBED & FACTS --> GEM
    AUTH -.-> SUPA
    CFG -.->|loaded at import| FastAPI & Agents & Tools & Workers
```

## 2. Meal-logging graph (LangGraph, interrupt-based)

```mermaid
stateDiagram-v2
    [*] --> router
    router --> classify: image_b64 present
    router --> extract: text only
    classify --> extract: food identified
    classify --> [*]: no food in image
    extract --> usda_batch
    usda_batch --> present
    present --> INTERRUPT: confirmation card shown,\nstate checkpointed to Postgres
    INTERRUPT --> intent_router: user replies\n(graph resumed)
    intent_router --> log: confirm keywords
    intent_router --> apply_correction: anything else\n(treated as correction)
    intent_router --> cancel: reject keywords
    apply_correction --> usda_batch: re-resolve & re-present
    log --> [*]: Postgres insert + Redis incr\n+ embed task enqueued
    cancel --> [*]
```

Key property: the conversation can span multiple HTTP requests. The graph
pauses after `present` and its full state is checkpointed (AsyncPostgresSaver,
keyed by `thread_id` = conversation_id). The orchestrator always resumes a
paused graph before re-classifying intent — a "how much protein is that?"
mid-confirmation is treated as a correction/reply, not a new coaching query.

## 3. Message routing decision

```mermaid
flowchart TD
    MSG[Incoming message] --> P{Graph paused\nfor this thread?}
    P -->|yes| RESUME[Resume meal-logging graph\nnever reclassify mid-confirmation]
    P -->|no| IMG{Image attached?}
    IMG -->|yes| FRESH[Fresh meal-logging run]
    IMG -->|no| KW{Keyword pre-filter\nrouting.query_signals /\nrouting.log_signals}
    KW -->|query signal| COACH[CoachingAgent]
    KW -->|log signal| FRESH
    KW -->|ambiguous| LLM[Flash-lite intent LLM\nstructured output]
    LLM -->|coaching| COACH
    LLM -->|log_meal| FRESH
```

## 4. Coaching data-fetch decision table

| Query shape | Source |
|---|---|
| today + macros only | Redis `today:{user}` (Postgres fallback on Redis error) |
| any other date range, macros | Postgres `SUM` over `meal_log` |
| any micronutrient | Postgres JSONB `jsonb_array_elements(entities)` |
| `include_goals` | Postgres `user_goal` |

The response LLM (Gemini 2.5 Flash) only ever sees fetched data — the system
prompt forbids inventing numbers, and graceful "no data" replies short-circuit
before the LLM is called.

## 5. Memory layers (PRD §5.1)

| Layer | Storage | Writer | Reader | Status |
|---|---|---|---|---|
| Session (today totals) | Redis, TTL 24h | `log_meal` | coaching, dashboard | ✅ |
| Episodic (meals) | `meal_log` + embedding | `log_meal` + `embed_meal_summary` | `get_history` | ✅ |
| Semantic (preferences) | `user_memory` + pgvector | `extract_and_store_facts` | `build_context` ANN | ⚠️ task exists, not yet enqueued |
| Procedural (templates) | `meal_template` | — | — | deferred (post-MVP) |
| Long-term patterns | `daily_summary` / `weekly_summary` | nightly/weekly crons | `build_context` | ✅ |

## 6. Configuration

All prompts, model names, token limits, and behavioural thresholds live in
**`src/backend/config/tunables.yaml`**, documented inline per key. Loaded once
per process through `backend.config.get_tunables()` (Pydantic-validated:
unknown keys or wrong types fail at startup, not mid-request). Restart
uvicorn + celery after editing. `NUTRICHAT_TUNABLES_PATH` env var points to an
alternative file for prompt experiments.

Secrets and infrastructure endpoints stay in `.env` (see CLAUDE.md) — the
YAML holds behaviour, not credentials.

## 7. Idempotency & failure properties

| Operation | Property |
|---|---|
| `aggregate_daily_summary` / `build_weekly_summary` | Idempotent — `ON CONFLICT … DO UPDATE` upserts; safe to re-run for any date |
| `embed_meal_summary` | Idempotent — overwrites `meal_log.embedding`; no-op if meal deleted |
| `extract_and_store_facts` | Convergent — cosine-distance dedup (< 0.05) suppresses near-duplicates |
| `reset_day_keys` | Idempotent — Redis DELETE |
| USDA cache write | Idempotent — `ON CONFLICT (fdc_id) DO NOTHING` |
| `log_meal` | **Not idempotent** — but protected by graph structure: the `log` node runs at most once per confirmation interrupt; a second "yes" on the same thread finds the graph at END and starts a fresh extraction instead |
| Postgres insert + Redis increment | Not atomic — if Redis fails after the insert, today's totals undercount until the nightly aggregate; Postgres is the source of truth |
| Celery task DB engine | Each task runs in a fresh event loop and disposes the engine afterwards (`_run()` wrapper) — prevents cross-loop asyncpg failures |
