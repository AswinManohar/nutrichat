# NutriChat — Product Requirements Document

**Version:** 2.0 — March 2026
**Status:** Active Development
**Scope:** MVP — Phase 1–2 (18 weeks)
**Stack:** Python · FastAPI · LangGraph · React
**LLM:** Gemini 3.1 Flash-Lite (extraction) · Gemini 2.5 Flash (coaching)
**Database:** PostgreSQL 16 + pgvector · Redis
**Food data:** USDA FoodData Central (CC0, free)

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [Problem statement](#2-problem-statement)
3. [Solution architecture](#3-solution-architecture)
4. [Technology stack](#4-technology-stack)
5. [Memory & context architecture](#5-memory--context-architecture)
6. [User personas](#6-user-personas)
7. [Feature specification](#7-feature-specification)
8. [Database schema](#8-database-schema)
9. [Project timeline](#9-project-timeline--18-weeks-to-mvp)
10. [Detailed implementation plan](#10-detailed-implementation-plan)
11. [Evaluation targets](#11-evaluation-targets)
12. [Latency budget](#12-latency-budget)
13. [Risks & mitigations](#13-risks--mitigations)
14. [Open questions](#14-open-questions)

---

## 1. Executive summary

> **Product north star:** NutriChat delivers USDA-verified calorie and macro tracking via natural language in under 15 seconds per meal — at zero data-source cost, with a monthly infrastructure bill under €80 for the first 1,000 active users.

The core problem NutriChat solves: every existing nutrition app either relies on photo-AI estimation (15–30% calorie error, per USDA benchmarks) or requires manual database search (5–15 minutes per meal). NutriChat routes around both failure modes by using natural language extraction grounded exclusively in USDA FoodData Central — a CC0 public domain database with 380,000+ lab-analysed foods.

The agent architecture is built for learning: a LangGraph tool-use router with four tools (`extract_entities`, `usda_lookup_batch`, `log_meal`, `get_history`), a four-layer memory system (Redis session, Postgres episodic, pgvector semantic, pre-aggregated weekly), and a context engineering strategy that keeps the system prompt under 480 tokens regardless of how much history the user has.

---

## 2. Problem statement

### 2.1 Photo AI failure mode

Photo-based calorie estimation — the dominant 2025–2026 innovation — introduces 15–30% calorie variance from portion estimation errors, food occlusion, and lighting conditions. Yazio's own UI labels photo results "rough estimate only." For users managing health conditions or serious fitness goals, this error margin erases the clinical utility of tracking.

### 2.2 Manual search friction

Manual search requires the user to know the USDA-style food name, find the right entry among dozens of near-duplicates, and select the correct portion size. Average time: 5–15 minutes per meal. This causes the most motivated users to abandon tracking within 2 weeks (JMIR 2024, n=31,971).

### 2.3 The gap NutriChat fills

A text interface where the user types what they actually say — "had 2 scrambled eggs and toast" — and the agent handles the rest: entity extraction, USDA matching, quantity normalisation, calorie computation, and logging. Under 15 seconds, USDA-verified, no estimation.

---

## 3. Solution architecture

### 3.1 High-level architecture

```
React frontend → FastAPI → Orchestrator [build_context + build_system_prompt]
  → LangGraph agent [extract → usda_lookup_batch → log_meal]
  → PostgreSQL + pgvector + Redis
```

### 3.2 Component map

| Component | Technology | Purpose | File |
|---|---|---|---|
| API layer | FastAPI (Python 3.12) | Receives requests, validates auth, routes to orchestrator | `api/meals.py` |
| Orchestrator | Python | Builds context + system prompt, invokes LangGraph graph | `agent/orchestrator.py` |
| Context builder | Python | Reads Redis + Postgres + pgvector to assemble 480-token prompt | `agent/context.py` |
| LangGraph agent | LangGraph + Gemini | Tool-use router: extract → lookup → log | `agent/graph.py` |
| Entity extraction | Gemini 3.1 Flash-Lite | Parses free text → `[{food_name, qty_g, confidence}]` | `agent/tools/meals.py` |
| USDA lookup | aiohttp + Postgres cache | Parallel FDC fetch, cache-first, scales nutrients by `qty_g` | `agent/tools/usda.py` |
| Meal logging | psycopg2 + Redis pipeline | Writes `meal_log` row + increments Redis session totals | `agent/tools/meals.py` |
| History retrieval | pgvector + SQL | Hybrid: vector ANN + SQL WHERE filters | `agent/tools/history.py` |
| Session memory | Redis (TTL 24h) | Today's running totals — never re-aggregated at request time | `db/redis_client.py` |
| Semantic memory | PostgreSQL + pgvector | User preferences embedded and retrieved by similarity | `db/models.py` |
| Background jobs | Celery + Redis | Embedding, fact extraction, daily/weekly aggregation | `workers/tasks.py` |
| Frontend | React 19 + TypeScript | Chat UI, dashboard, macro charts, PWA | `frontend/src/` |

### 3.3 Data flow — one meal log

1. User types "had 2 scrambled eggs and toast for breakfast"
2. FastAPI validates JWT, calls `orchestrator.handle_message()`
3. `build_context()`: reads Redis today totals + Postgres goals + pgvector top-3 preferences
4. `build_system_prompt()`: assembles 456-token prompt with live state
5. `graph.ainvoke()` — Turn 1: LLM calls `extract_entities` → `[{egg, 122g}, {bread, 28g}]`
6. Turn 2: LLM calls `usda_lookup_batch([{egg,122g},{bread,28g}])` — both FDC lookups fire in parallel
7. LLM presents results, asks confirmation (251 kcal, 16g protein)
8. User confirms → LLM calls `log_meal` → Postgres row written + Redis totals incremented
9. Celery queues: `embed_meal_summary` (async) + `extract_and_store_facts` (async)

### 3.4 Multi-agent architecture (Phase 2)

The single agent splits into three specialists routed by an orchestrator classifier:

```
user message → orchestrator (classify intent)
                    ├── log_meal    → logging agent   (Flash-Lite · 3 tools · minimal context)
                    ├── coaching    → coaching agent  (Gemini 2.5 Flash · 2 tools · full history)
                    └── recipe      → recipe agent    (Gemini 2.5 Flash · 3 tools · budget-aware)
```

**Why split:** the coaching agent needs 30 days of meal history; the logging agent needs almost none. Mixing them bloats every meal log call with context it doesn't use. Agents never call each other — all cross-agent coordination goes through the orchestrator.

| Agent | Trigger | Model | Tools | Context injected |
|---|---|---|---|---|
| Logging | "had eggs and toast" | Flash-Lite | extract, usda_batch, log_meal | Today totals + goals (~130 tokens) |
| Coaching | "what should I eat?" | Gemini 2.5 Flash | get_history, get_remaining_budget | Full weekly + prefs (~320 tokens) |
| Recipe | "what can I make with chicken?" | Gemini 2.5 Flash | search_ingredients, usda_nutrition_check, get_remaining_budget | Remaining budget + restrictions (~120 tokens) |

---

## 4. Technology stack

### 4.1 Backend

| Layer | Technology | Justification | Monthly cost (1k users) |
|---|---|---|---|
| API framework | FastAPI (Python 3.12) | Async-native, Pydantic validation, auto OpenAPI docs | Free |
| LLM — extraction | Gemini 3.1 Flash-Lite | 4× cheaper than Claude Haiku. 97% JSON compliance. 363 tok/sec. | €5–15 |
| LLM — coaching | Gemini 2.5 Flash | 10× cheaper than Sonnet. 1M context. Adjustable reasoning depth. | €3–10 |
| LLM — fallback | Claude Haiku 4.5 | Better instruction fidelity on hard extractions. Pro tier users. | €2–5 |
| Primary database | PostgreSQL 16 + pgvector | One service: relational + vector + JSON. No separate vector DB needed. | €15 managed |
| Session cache | Redis (Upstash serverless) | Today's running totals. `HINCRBYFLOAT` atomic. TTL 24h. Sub-10ms reads. | €0–10 |
| Task queue | Celery + Redis | Background: embedding, fact extraction, nightly aggregation | Included in Redis |
| Embeddings | Gemini text-embedding-005 | $0.006/M tokens. 768-dim. Free tier 1,500 req/day covers MVP. | €1–3 |
| Auth | Supabase Auth | Managed JWT. Free tier 50k MAU. Social login. | €0 |
| Food data | USDA FoodData Central API | CC0 public domain. 380k+ lab-analysed foods. Free forever. | Free |
| Hosting | Railway (backend) + Vercel (frontend) | Git-deploy. Auto-scaling. No DevOps. | €20–40 |

### 4.2 Frontend

| Layer | Technology | Purpose |
|---|---|---|
| Framework | React 19 + TypeScript | Type-safe UI, hooks, modern async patterns |
| Build | Vite | Sub-second HMR, fast production builds |
| Styling | Tailwind CSS v4 | Utility-first, no runtime CSS |
| Components | shadcn/ui | Accessible, unstyled, copy-paste — no vendor lock-in |
| State | Zustand | Lightweight (1kb), no boilerplate |
| Data fetching | TanStack Query v5 | Optimistic updates, caching, streaming |
| Charts | Recharts | Macro bars, weekly trend lines, calorie ring |
| PWA | Vite PWA plugin | Offline queue, installable, push notifications |

### 4.3 Cost model

| User scale | Infrastructure | LLM (Gemini) | Total / month |
|---|---|---|---|
| 0–1k users (prototype) | Railway Starter €5 | ~€5–15 | ~€11–21 |
| 1k–10k users (MVP) | Railway Pro €20 | ~€40–100 | ~€100–160 |
| 10k–50k users (growth) | Render Standard €85 | ~€200–500 | ~€435–735 |
| 50k+ users | Hetzner VPS cluster €80 | ~€800–1,500 | ~€970–1,670 |

---

## 5. Memory & context architecture

### 5.1 Five memory layers

| Layer | Storage | What it holds | Written by | Read by |
|---|---|---|---|---|
| Session (working) | Redis TTL 24h | Today's kcal, protein, fiber, n_meals | `log_meal` tool | `build_context()` |
| Episodic | Postgres `meal_log` | Every meal with nutrients, embedding, flags | `log_meal` tool | `get_history` tool |
| Semantic | Postgres `user_memory` + pgvector | Preference facts: "prefers oat milk" | Celery: `extract_and_store_facts` | `build_context()` via ANN |
| Procedural | Postgres `meal_template` | Named templates: "usual lunch" | Celery: `check_meal_template` | `orchestrator.py` |
| Long-term patterns | Postgres `weekly_summary` | Avg macros, days hit goals, weak spots | Celery: `build_weekly_summary` | `build_context()` |

### 5.2 Context window budget (480 tokens)

| Block | Source | Tokens | Always injected? |
|---|---|---|---|
| Role + tone | Static string | ~120 | Yes |
| Today totals | Redis `HGETALL` | ~80 | Yes |
| Weekly pattern | Postgres `weekly_summary` | ~120 | Yes |
| User preferences | pgvector top-3 ANN | ~150 | Only when `user_message` given |
| Accountability rules | Static + conditional | ~95 | Yes (rule 5 conditional on time + state) |
| Hard constraints | Static string | ~112 | Yes |
| **Total (with prefs)** | | **~456** | **Within budget** |

---

## 6. User personas

### Alex, 32 — fitness / body composition

| Attribute | Detail |
|---|---|
| Goal | Gain lean muscle. Targets 140g protein/day, 1,900 kcal. |
| Behaviour | Logs 3–4 meals/day. Gym 5×/week. Uses protein shakes post-workout. |
| Pain point | Existing apps don't remember he always has oat milk. Re-entering "usual lunch" takes 3 minutes. |
| NutriChat value | One-word re-log via meal templates. Post-workout shake recognised from history. Protein alerts by 6pm. |
| Success metric | Logs consistently for 14+ days. Protein goal hit rate increases week-over-week. |

### Maria, 45 — type 2 diabetes management

| Attribute | Detail |
|---|---|
| Goal | Control blood glucose via diet. Targets <150g carbs/day, 30g fiber. |
| Behaviour | Logs every meal carefully. Tracks fiber specifically. Avoids processed foods. |
| Pain point | Apps don't show fiber prominently. No guidance on carb timing relative to meals. |
| NutriChat value | Fiber tracked alongside macros. Coaching messages reference her specific fiber patterns. Weekly pattern identifies carb spikes. |
| Success metric | Fiber goal hit rate ≥70% of days. Continues using after 30 days. |

---

## 7. Feature specification

### Phase 1 MVP — core logging loop

| Feature | Description | Acceptance criteria |
|---|---|---|
| F1 — Text meal logging | User describes meal in natural language. Agent extracts entities, resolves to USDA, presents confirmation card. | P95 < 3s. USDA match rate ≥90%. Entity F1 ≥0.88. |
| F2 — Image logging | User uploads photo. Agent classifies food items, then proceeds to text extraction flow. | Image classification returns `food_items` list. Proceeds to entity extraction. |
| F3 — Daily dashboard | Shows today's kcal, protein, fiber as ring charts. Meal timeline below. | Totals match Redis session state. Updates within 500ms of log. |
| F4 — Goal setup | Onboarding: TDEE calc, macro targets, dietary prefs. Completion < 90 seconds. | Completion rate ≥70% in user testing (n=10). |
| F5 — USDA cache | First FDC lookup cached in Postgres. Subsequent lookups read from cache. | Cache hit rate ≥90% after 48h steady-state. |

### Phase 2 — memory & personalisation

| Feature | Description | Acceptance criteria |
|---|---|---|
| F6 — Preference memory | Agent extracts and stores preference facts. Retrieved on each turn. | After stating "I always use oat milk", preference appears in next session. |
| F7 — Meal templates | Repeated meals auto-saved as named templates. One-word re-log. | "Usual lunch" → confirmation card in < 500ms, no LLM call. |
| F8 — Coaching messages | Daily accountability message grounded in logged data. Protein alert by 6pm. | Messages rated ≥4/5 by reviewers. No unsafe recommendations. |
| F9 — Weekly check-in | Monday summary: adherence rate, patterns, one accountability question. | Protein adherence rate and weak spot correctly identified from `weekly_summary`. |
| F10 — Pro tier | Stripe paywall. Pro users get Haiku/Sonnet instead of Flash-Lite/Flash. | Conversion ≥5% of free users within 30 days of paywall launch. |

---

## 8. Database schema

> **Key constraint:** Six tables. One Alembic migration. pgvector extension required. Never re-aggregate `meal_log` at request time — all totals come from Redis or pre-aggregated Postgres rows.

| Table | Type | Key columns | Written by | Read by |
|---|---|---|---|---|
| `user_goal` | Postgres | `kcal_goal`, `protein_goal`, `fiber_goal`, `dietary_prefs`, `streak_days` | Onboarding API | `build_context()` |
| `meal_log` | Postgres + pgvector | `meal_id`, `user_id`, `logged_at`, `meal_type`, `kcal`, `protein_g`, `fiber_g`, `entities JSONB`, `embedding vector(768)`, `flags JSONB` | `log_meal` tool | `get_history` tool |
| `user_memory` | Postgres + pgvector | `id`, `user_id`, `fact`, `embedding vector(768)`, `category`, `confidence`, `updated_at` | Celery: `extract_and_store_facts` | `build_context()` ANN search |
| `food_source` | Postgres | `fdc_id`, `food_name`, `nutrients JSONB`, `nutrients_count`, `data_quality`, `source_db` | `usda_lookup_batch` (cache miss) | `usda_lookup_batch` (cache hit) |
| `daily_summary` | Postgres | `user_id`, `date`, `kcal`, `protein_g`, `fiber_g`, `protein_goal_hit`, `has_veg_day` | Celery: `aggregate_daily_summary` (midnight) | `build_context()` Redis fallback |
| `weekly_summary` | Postgres | `user_id`, `week_start`, `avg_protein_g`, `days_hit_protein`, `weak_spots[]`, `missed_meals[]` | Celery: `build_weekly_summary` (Sunday) | `build_context()` weekly block |

### Key indexes

```sql
ix_meal_log_user_logged_at   — (user_id, logged_at DESC)               — time-range queries
ix_meal_log_user_protein     — (user_id, protein_g)                    — nutrient filter queries
ix_meal_log_hybrid           — (user_id, meal_type, protein_g, logged_at DESC) — hybrid queries
ix_meal_log_embedding        — IVFFlat on embedding, vector_cosine_ops, lists=100
ix_user_memory_embedding     — IVFFlat on embedding, vector_cosine_ops, lists=100
```

---

## 9. Project timeline — 18 weeks to MVP

> **Phase gate policy:** Three phases with hard gates. Phase 2 does not start until all Phase 1 milestones pass. No skipping ahead — each phase depends on the previous one being genuinely working, not just present.

---

### Phase 1 — foundation: storage + core pipeline (weeks 1–6)

#### Week 1–2 — storage foundation

**Alembic migration (`001_initial.py`)** — `db/migrations/versions/001_initial.py` · `alembic.ini` · `db/migrations/env.py`
- `CREATE EXTENSION vector; CREATE EXTENSION pgcrypto`
- 6 tables: `user_goal`, `meal_log`, `user_memory`, `food_source`, `daily_summary`, `weekly_summary`
- 13 B-tree indexes + 2 IVFFlat pgvector indexes
- Verify with: `python db/verify_schema.py`

**SQLAlchemy models** — `db/models.py`
- ORM classes for all 6 tables
- JSONB columns mapped to Python dicts
- UUID primary keys via `gen_random_uuid()`

**Redis session helpers** — `db/redis_client.py`
- `get_redis()` connection pool
- `get_today_totals(user_id)` → `TodayTotals`
- `increment_today(user_id, meal)` — pipeline `HINCRBYFLOAT`
- `reset_day_key()` — called at midnight by Celery beat

#### Week 3–4 — core agent pipeline

**USDA cache-first lookup + parallel batch** — `agent/tools/usda.py`
- `usda_lookup_batch(entities: list[dict]) → list[dict]`
- Postgres `food_source` check before API call
- `aiohttp` parallel FDC requests via `asyncio.gather`
- Cache write on miss: `INSERT INTO food_source ... ON CONFLICT DO NOTHING`
- Nutrient scaling: `kcal = kcal_per_100g * qty_g / 100`

**`log_meal` tool with real DB writes** — `agent/tools/meals.py`
- Postgres `meal_log` INSERT (meal_id, user_id, logged_at, meal_type, totals, entities JSONB, flags JSONB)
- Redis pipeline: `HINCRBYFLOAT` ×5 nutrients + `EXPIRE 86400`
- `Celery.send_task('embed_meal_summary', args=[meal_id])`
- `Celery.send_task('extract_and_store_facts', args=[user_id, user_input, reply])`

**Wire `context.py` into LangGraph agent** — `agent/graph.py` · `agent/context.py` · `agent/orchestrator.py`
- `AgentState`: `messages`, `user_id`, `system_prompt` fields
- `call_model()` reads `state['system_prompt']` instead of hardcoded string
- `orchestrator.handle_message()` calls `build_context()` then `graph.ainvoke()`
- `config={'configurable': {'user_id': user_id}}` threads `user_id` to tools via `RunnableConfig`

#### Week 5–6 — API layer + phase 1 exit

**FastAPI endpoints** — `api/meals.py` · `api/goals.py` · `main.py`
- `POST /meals/log` — auth middleware → `orchestrator.handle_message()` → stream response
- `GET /dashboard/today` — reads Redis session totals
- `GET/PUT /goals` — reads/writes `user_goal` table
- Supabase Auth JWT middleware on all routes

**Phase 1 exit criteria (all must pass)**
- E2E meal log P95 < 3s verified by Locust (10 concurrent users)
- USDA cache hit rate ≥90% over 100 test requests
- Entity F1 ≥0.80 on 50-item manually graded test set
- User A cannot read User B's `meal_log` rows (automated API test)
- Onboarding completion ≥70% in 10-user internal beta

---

### Phase 2 — memory + personalisation + monetisation (weeks 7–12)

#### Week 7–8 — semantic memory layer

**`extract_and_store_facts` Celery task** — `workers/tasks.py`
- Calls Gemini to extract preference facts from `(user_input, agent_reply)` pair
- Embeds each fact via Gemini `text-embedding-005` (768-dim)
- Deduplication: `SELECT ... WHERE embedding <=> $vec < 0.05` before INSERT
- `UPDATE updated_at` if near-duplicate exists (bump timestamp, don't insert)

**`embed_meal_summary` Celery task** — `workers/tasks.py`
- Generates summary string: "High-protein breakfast: eggs, toast. 251 kcal, 16g protein."
- Embeds via Gemini `text-embedding-005`
- `UPDATE meal_log SET embedding = $vec WHERE meal_id = $id`

**`get_history` hybrid retrieval tool** — `agent/tools/history.py`
- Embeds query string via Gemini embeddings
- pgvector ANN + SQL WHERE: `user_id`, `meal_type`, `protein_g`, `logged_at` range
- Returns top-3 meals ranked by cosine similarity within filters
- Falls back to pure SQL if no semantic query provided (cheaper)

#### Week 9–10 — templates + coaching

**Meal templates (procedural memory)** — `workers/tasks.py` · `agent/tools/meals.py`
- `check_meal_template` Celery task: detect 3+ identical meals → auto-create template
- `meal_template` table: `name`, `foods JSONB`, `nutrients JSONB`, `use_count`
- Template matching in orchestrator before LLM call (< 500ms, no LLM)
- Explicit save: "save this as gym breakfast" → `INSERT INTO meal_template`

**Proactive coaching + weekly check-in** — `agent/coaching.py` · `workers/tasks.py`
- 6pm Celery beat trigger: check Redis totals, generate alert if protein < 60% goal
- Monday check-in: reads `weekly_summary`, generates adherence summary + one question
- All coaching grounded in logged data (system prompt constraint enforced)
- Coaching messages rated by internal reviewer before each weekly release

#### Week 11–12 — aggregation + monetisation

**Nightly + weekly Celery jobs** — `workers/tasks.py`
- `aggregate_daily_summary`: runs 00:05 daily, reads `meal_log`, writes `daily_summary` row
- `build_weekly_summary`: runs Sunday 23:00, reads `daily_summary`, writes `weekly_summary` row
- `reset_day_keys`: runs 00:00 daily, expires Redis session keys for all active users
- Never re-aggregates `meal_log` rows at request time — only these Celery jobs do that

**Stripe Pro tier + paywall** — `api/billing.py` · `frontend/src/components/Paywall.tsx`
- Pro tier: €4.99/month. Routes to Haiku 4.5 (extraction) + Sonnet 4.6 (coaching).
- Free tier: Gemini Flash-Lite + Gemini 2.5 Flash.
- Paywall screen shown when free user requests weekly insights.
- Phase 2 exit: ≥40% Day-14 retention, ≥5% Pro conversion, zero cross-user memory leaks.

---

## 10. Detailed implementation plan

### 10.1 File structure at MVP

```
backend/
├── api/
│   ├── meals.py          # POST /meals/log, GET /dashboard/today
│   ├── goals.py          # GET/PUT /goals
│   └── billing.py        # Stripe webhook + subscription check
├── agent/
│   ├── orchestrator.py   # handle_message(), main entry point
│   ├── context.py        # build_context(), build_system_prompt()
│   ├── graph.py          # LangGraph StateGraph with 4 tools
│   ├── coaching.py       # proactive coaching message generator
│   └── tools/
│       ├── meals.py      # extract_entities, log_meal tools
│       ├── usda.py       # usda_lookup_batch parallel tool
│       └── history.py    # get_history hybrid search tool
├── agents/               # Phase 2 — multi-agent split
│   ├── logging_agent.py
│   ├── coaching_agent.py
│   └── recipe_agent.py
├── db/
│   ├── models.py         # SQLAlchemy ORM models
│   ├── redis_client.py   # Redis connection + session helpers
│   └── migrations/
│       ├── env.py
│       └── versions/
│           └── 001_initial.py
├── workers/
│   └── tasks.py          # All Celery tasks
└── main.py               # FastAPI app + middleware

frontend/src/
├── components/
│   ├── ChatInput.tsx         # message input with streaming
│   ├── ConfirmationCard.tsx  # meal review before logging
│   ├── Dashboard.tsx         # today view with macro rings
│   ├── MacroRings.tsx        # kcal/protein/fiber progress rings
│   └── WeeklyChart.tsx       # 7-day bar chart
├── stores/
│   └── mealStore.ts          # Zustand meal + session state
└── api/
    └── client.ts             # TanStack Query hooks
```

### 10.2 Build order and dependencies

| Step | Task | Depends on | Verifiable exit |
|---|---|---|---|
| 1 | Postgres schema (Alembic 001) | Nothing | `python db/verify_schema.py` passes |
| 2 | Redis helpers | Nothing | `HGETALL` returns `TodayTotals` dataclass |
| 3 | USDA cache-first lookup | Step 1 (`food_source` table) | Cache hit + miss both return correct nutrients JSON |
| 4 | `log_meal` with DB writes | Steps 1, 2, 3 | Row appears in `meal_log`; Redis totals increment |
| 5 | `build_context()` + `build_system_prompt()` | Steps 1, 2 | Prompt assembles under 480 tokens with live state |
| 6 | LangGraph graph wired to context | Steps 3, 4, 5 | End-to-end: type meal, see confirmation card, log |
| 7 | FastAPI `/meals/log` endpoint | Step 6 | HTTP 200 from curl with auth token |
| 8 | React chat UI | Step 7 | User can type, confirm, and see updated dashboard |
| 9 | `extract_and_store_facts` task | Steps 1, 6 | Fact appears in `user_memory` after conversation |
| 10 | `embed_meal_summary` task | Steps 1, 6 | `meal_log.embedding` column populated within 5s |
| 11 | `get_history` hybrid search | Steps 9, 10 | "high-protein breakfasts last week" returns correct meals |
| 12 | Meal templates | Steps 1, 4, 11 | "usual lunch" logs in < 500ms without LLM call |
| 13 | Nightly aggregation jobs | Steps 1, 4 | `daily_summary` + `weekly_summary` rows created by Celery |
| 14 | Coaching + weekly check-in | Steps 5, 13 | Monday message contains correct adherence rate |
| 15 | Stripe Pro tier | Step 7 | Free vs Pro routes to different models |

---

## 11. Evaluation targets

> **Benchmark target:** Beat NutriRAG (JAMIA 2026) micro-F1 of 82.24 on entity extraction.
> Run: `python eval/run_eval.py --dataset eval/test_set_200.jsonl`

| Metric | Target | NutriRAG baseline | How measured |
|---|---|---|---|
| Entity Extraction F1 | ≥0.88 | 0.8224 (GPT-4+RAG) | 200-item manually annotated test set |
| USDA Match Rate | ≥90% | Not measured | 100-item test set with gold FDC IDs |
| Calorie MAE | ≤50 kcal | Not measured | 30 weighed-ingredient meals |
| RAG Faithfulness | ≥95% | Not measured | RAGAS faithfulness on 100 coaching samples |
| Coverage | ≥95% | Not measured | % inputs returning ≥1 entity |
| Latency P95 | < 3,000ms | Not measured | Locust: 10 concurrent users |
| USDA Cache Hit | ≥90% | Not measured | Request log analysis over 48h |
| Day-14 Retention | ≥40% | Not measured | Supabase analytics events |

---

## 12. Latency budget

| Operation | Target P95 | Approach |
|---|---|---|
| Entity extraction (Gemini Flash-Lite) | < 1,500ms | Haiku fallback at 3s. Keep system prompt < 500 tokens. |
| USDA FDC lookup (per entity, parallel) | < 300ms | Cache-first. 90%+ hit rate eliminates API latency. |
| pgvector ANN search (user preferences) | < 50ms | IVFFlat index. < 1M vectors at MVP. |
| Redis session totals read | < 10ms | `HGETALL` on single hash key. Sub-millisecond typical. |
| Celery task queue (embed + facts) | < 5s async | Non-blocking. User reply not delayed by background work. |
| Full message → confirmation card | < 3,000ms | Parallel FDC. Streaming first token. Optimistic UI. |

---

## 13. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Gemini Flash-Lite JSON verbosity | High | Medium | Hard `max_output_tokens`. Stop sequences. Fall back to Haiku for structured tasks if F1 drops below 0.80. |
| USDA FDC rate limit (1k req/hr) | Low | Medium | Postgres cache eliminates 90%+ of calls. Contact FDC for limit increase (free on request). |
| Entity extraction F1 below 0.88 | Medium | High | Weekly eval on 50 real descriptions. Prompt iteration sprint if below threshold. |
| pgvector slow at scale | Low | Low | IVFFlat handles < 1M vectors. Migration to Qdrant documented if needed. |
| Celery task backlog under load | Medium | Medium | Separate queues: embedding (low priority), facts (medium), aggregation (high). Monitor queue depth. |
| LLM coaching hallucination | Low | High | System prompt: "only cite logged data or USDA". Nutrient Safety custom metric in eval. Human review weekly. |
| NCCDB licensing | Low | Low | Use USDA FDC Foundation Foods (lab-analysed, same quality). Do not use NCCDB without UMN license. |

---

## 14. Open questions

1. **Voice input:** should Phase 2 include voice-to-text meal logging? Whisper API or browser Web Speech API?
2. **Barcode scanning:** Open Food Facts integration planned for Phase 3. Include partial implementation in Phase 2?
3. **Meal template auto-naming:** should the agent suggest a name ("gym breakfast?") or require the user to name it?
4. **Coaching frequency:** daily message vs on-demand only? Daily may increase churn if tone is wrong.
5. **Multi-source databases:** CNF (Canada), CoFID (UK), NEVO (Netherlands) — which market to target first for Phase 2?

---

*NutriChat PRD v2.0 · March 2026 · Learning project — agentic systems development*
