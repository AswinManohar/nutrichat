# Mealsy — System Architecture

Status: describes the code on `feat/coaching-telegram-estimation-deploy` as of 2026-08-29.
Everything here is derived from the source; paths are relative to `src/backend/` unless stated.

## 1. One-paragraph summary

Mealsy is a nutrition-logging agent. A user describes a meal in natural language
(web chat or Telegram, optionally with a photo). A LangGraph state machine extracts
food entities with Gemini 2.5 Flash, resolves each against a bundled USDA FoodData
Central SQLite database (falling back to the FDC API, then to an LLM estimate),
pauses for user confirmation, and writes a `meal_log` row. Daily totals live in Redis
as a write-through cache over Postgres. Coaching questions ("how am I doing on
protein?") go to a separate Pydantic AI agent. Celery beat tasks produce daily /
weekly summaries, nutrient checkups, and Telegram digests overnight.

## 2. Runtime topology

```
Browser (React SPA, Netlify)  ──JWT──▶  ┌──────────────────────────────┐
Telegram (webhook in prod)    ─────────▶ │ web   : FastAPI + uvicorn    │
                                         │ worker: Celery (2 procs)     │──▶ Redis (Railway plugin)
                                         │ bot   : aiogram polling (dev)│      broker + result + cache
                                         └──────────────┬───────────────┘
                                                        │ psycopg / asyncpg
                                            Supabase Postgres 16 + pgvector
                                            Supabase Auth (ES256 JWKS)
External: Gemini API · USDA FDC API (fallback only) · Logfire · Web Push (VAPID)
```

One container image (`nixpacks.toml`, python 3.13 + uv) is deployed as three Railway
services; `start.sh` dispatches on `PROC=web|worker|bot`. Prod Telegram traffic
enters the **web** service at `POST /telegram/webhook` when `TELEGRAM_USE_WEBHOOK=true`;
the separate `bot` service is the dev/polling path. Migrations are applied manually
against Supabase, not at release (`Procfile` note).

## 3. Backend (FastAPI)

`main.py` — `FastAPI(title="Mealsy")`. Lifespan opens one `pooled_checkpointer()`
(psycopg pool, min 1 / max 4, `SELECT 1` health check) onto `app.state.checkpointer`.

Middleware (outermost first): `CORSMiddleware(FRONTEND_ORIGIN + localhost regex)`
→ `RateLimitMiddleware` (Redis fixed window, `ratelimit:{scope}:{identity}`,
120/min per IP, fails open, exempts `/health`).

| Router | Routes | Notes |
|---|---|---|
| `api/meals.py` `/meals` | `POST /log` · `POST /log-items` · `DELETE /log/{id}` · `GET /today` · `GET /categories` · `GET /trends` | `/log` is the agent entrypoint; per-user limiter 20/min |
| `api/goals.py` `/goals` | `GET · POST · PUT` | |
| `api/quota.py` `/quota` | `GET` | LLM credits on `user_goal` |
| `api/billing.py` `/billing` | `POST /upgrade` | |
| `api/my_meals.py` `/my-meals` | CRUD + `POST /{id}/log` | saved meals, embedded |
| `api/nutrient_checkup.py` | `GET ""` · `GET /pending-nudge` · `POST /pending-nudge/ack` | |
| `api/mindful.py` `/mindful` | `GET /today` | intake safety checks |
| `api/telegram_link.py` `/telegram` | `POST /link-code` · `GET /link` · `DELETE /link` | |
| `api/push.py` `/push` | `GET /vapid-public-key` · `POST /subscribe` | |
| `api/integrations.py` `/v1/integrations` | `GET /meals /daily-summary /weekly-summary /goals /health` | API-key auth |

Auth: `auth/supabase.py:get_current_user_id` verifies Supabase JWTs — ES256/RS256
via JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, cached by `kid`, one
refetch on miss), HS256 via `SUPABASE_JWT_SECRET`, audience `authenticated`.
`DEV_BYPASS_AUTH=true` + `X-Debug-User-Id` for local dev. Integrations use
`auth/integration.py:get_integration_user` — SHA-256 token hash vs
`integration_token.token_hash`, scope `nutrition:read`.

## 4. Agent layer

### 4.1 Orchestrator (`agent/orchestrator.py`)

`handle_message(user_id, user_input, thread_id, checkpointer, image_b64, meal_type, action)`

1. If the thread has a **paused graph** (interrupted after `present`), resume it — the
   message is a confirmation / correction / cancel. Resumes cost no quota.
2. Else if there is an image → meal logging.
3. Else `_classify_intent`: keyword prefilter (strong query signals → coaching,
   log signals → log_meal, weak query signals → coaching), then LLM tiebreak
   (`_IntentResult`, 200 output tokens).
4. `quota.consume_llm_credit` per fresh turn; over quota → upgrade message.
5. Every turn with user text fire-and-forgets `extract_and_store_facts.delay(...)`
   (kombu errors swallowed); card button presses and photo-only turns skip it.
   See 4.5 for what the task does.

Compiled graphs are cached per checkpointer identity.

### 4.2 Meal-logging graph (`agent/graph.py`, LangGraph)

State: `messages, user_id, image_b64, entities, usda_results, meal_type, action,
from_saved, meal_id, decomposed_entities`.

```
router ─image?─▶ classify ─▶ extract ─▶ auto_decompose ─▶ usda_batch ─▶ present ⏸
   └─text──▶ saved_lookup ─hit─▶ present                                   │
                  └─miss──▶ extract                                        ▼
                                                                    intent_router
             log ◀── confirm ─────────────────────────────────────────────┤
             apply_correction ─▶ usda_batch                               │
             decompose / combine ─▶ usda_batch                            │
             saved_lookup (new meal) ◀────────────────────────────────────┤
             cancel ─▶ END                                                 ┘
```

Compiled with `interrupt_after=["present"]`; the checkpointer persists the paused
state between HTTP requests (thread_id from the client, `tg:{chat_id}:{uuid}` for
Telegram). This is the human-in-the-loop seam: nothing is written until `log`.

### 4.3 Food resolution (`agent/tools/usda.py`, `usda_local.py`, `usda_match.py`)

```
entity ─▶ food_source cache (Postgres, pg_trgm) ─hit─▶ result
            └miss─▶ local SQLite FTS5 (bm25, pool 25) + substring rescue
                     ranked by confidence › head purity › coverage › bm25
                     └ confidence < 0.6 ─▶ FDC API (1 attempt, 4 s)  [if use_local_db=false / db missing]
                                            └ fail ─▶ LLM estimate (Gemini) ─▶ cached as source_db=llm
                                                        └ fail ─▶ _miss_result
```

The bundled DB is `data/usda_fdc.sqlite3` (~15 MB, 13.7k foods: Foundation + SR
Legacy + FNDDS), built by `scripts/build_usda_db.py`; nutrients stored zlib-compressed.
Read-only per-thread connections; override with `USDA_DB_PATH`. The FDC API is
flaky (random 404s) so the local DB is primary.

### 4.4 Coaching (`agent/coaching.py`, Pydantic AI)

`parse_query` (Gemini Flash, thinking off, structured `QueryParsed`) →
`fetch_data` (Postgres: `get_today_totals` for today/macro-only questions, else
`tools/history.py`) → `generate_response` (Gemini Flash, thinking **on**). Prompts
in `config/prompts/coaching_*.md`.

**Guideline retrieval and the feedback loop.** When `parse_query` sets
`needs_guidance`, `guidelines/retrieval.py` embeds the message and runs a
condition-filtered pgvector cosine search over `guideline_chunk` (the user's
`user_goal.conditions` map to chunk tags, always including `general`). It
fetches `retrieval.guideline_top_k` rows and drops anything scoring below
`retrieval.guideline_min_score`, so an uncovered question retrieves nothing
rather than the nearest irrelevant passage. Survivors are rendered as a
delimited, numbered reference block the model cites as `[n]`; the numbers are
mapped back to chunk ids by `extract_citations`. Retrieval is enrichment only —
any failure logs a warning and the coach answers without citations. Every
coaching turn is then persisted by `agent/coaching_store.py` as a
`coaching_response` row (query, parsed query, a snapshot of the passages shown,
citations, reply, model, trace id). The web UI rates it thumbs up/down with an
optional comment via `POST /coaching/{id}/feedback`, and
`guidelines/export_feedback.py` exports the rows as JSONL — the seed for a
coaching eval set.

### 4.5 Preference memory (`agent/memory.py`)

The coach keeps a small typed profile per user in `user_memory` and sees all of
it on every coaching turn. It is rolled out behind `memory.profile_enabled` and
`memory.profile_allowlist`; users not on it keep the legacy path (append-only
facts, top-3 by embedding similarity).

**What is in the profile**

| Part | Where it lives | Who changes it |
|---|---|---|
| Diet settings (vegetarian, gluten free, ...) | `user_goal.dietary_prefs` | Settings; chat statements that match a setting |
| Facts: restriction, dislike, like, habit, context | `user_memory` | curators, coach tools, `/memory` API |
| Staple foods per meal type | derived from `meal_log` on read, cached in Redis | nothing stores them |

**One write path.** Everything goes through `apply_ops(user_id, ops, actor)`,
which takes a per-user advisory lock and enforces:

- *Tighten only.* The background actors (`curator`, `weekly`) can add a
  restriction or switch a diet setting on. Changing or removing a restriction,
  or switching a setting off, is allowed only to the `user` actor.
- *Tombstones.* A fact the user removes keeps its row with `deleted_at` set, and
  is not learned again until the user states it again.
- *Cap.* At most `profile_max_facts` facts and `profile_max_chars` characters.
  On overflow the oldest inferred like/habit/context fact is evicted;
  restrictions and stated facts never are.

**Writers**

| Writer | When | Actor |
|---|---|---|
| `memory_curator.curate_turn` | Celery, after each turn (`extract_and_store_facts`) | `curator` |
| `memory_curator.infer_log_habits` | Celery, weekly, users with enough logged meals | `weekly` |
| `memory_tools` remember / forget / set_diet | in the coaching turn, on an explicit request | `user` |
| `DELETE /memory/{id}` | client | `user` |

**Read path and cost.** `build_context` loads the live facts with one indexed
query (no embedding call) and the staples from Redis, and
`render_profile_block` puts diet settings and restrictions first. The block is
capped, so prompt size does not grow with history. A coaching turn is still two
model calls; only an explicit remember/forget adds a third. Meal-logging turns
do not read the profile.

**Evals.** `eval/eval_profile_curator.py` (curator prompt) and
`eval/eval_profile_coaching.py` (restrictions respected, no spurious tool
calls, memory requests call the right tool). Both use live Gemini and no
database.

### 4.6 LLM config

`agent/llm.py` reads `config/tunables.yaml`: extraction `gemini-2.5-flash`
(thinking budget 0), coaching `gemini-2.5-flash`, embeddings
`gemini-embedding-001` @ 768 dims. No cross-provider fallback is wired. Costs recorded via `agent/cost.py` →
Logfire `llm_cost` + counter `gen_ai.cost_usd`. Override tunables with
`NUTRICHAT_TUNABLES_PATH`.

## 5. Data layer

### Postgres (Supabase, pgvector, pg_trgm) — `db/models.py`, alembic `001…011`

| Table | Role |
|---|---|
| `user_goal` | per-user goals, tracking mode, streak, `llm_requests_used/llm_quota` |
| `meal_log` | the ledger: macros, `entities` JSONB, `label`, `embedding vector(768)`, `flags`, `deleted_at` (soft delete); indexes for user+time, cursor, hybrid search |
| `food_source` | USDA / LLM-estimate cache keyed by `fdc_id`, GIN trigram on `food_name` |
| `user_meal` | "My Meals" saved recipes with embeddings |
| `user_memory` | the coach's preference profile: typed facts, source, tombstones (see 4.5) |
| `daily_summary`, `weekly_summary`, `nutrient_checkup` | worker outputs |
| `telegram_link`, `integration_token`, `push_subscription` | channel bindings |

LangGraph checkpoints live in the same DB (`AsyncPostgresSaver` tables).
Day boundary: `Europe/Oslo`, resets at 01:00 (`current_day_bounds()`).

### Redis — `db/redis_client.py`

| Key | Purpose | TTL |
|---|---|---|
| `ratelimit:{scope}:{identity}` | fixed-window counters | window |
| `tgthread:{chat_id}` / `tgedit:{chat_id}` | Telegram thread + edit state | 24 h / 30 min |
| `tglink:code:*` | account-link codes | short |
| `staples:{user_id}` | staple foods per meal type for the coach prompt | 6 h |
| Celery broker + result backend | | |

## 6. Workers (`workers/tasks.py`, Celery "nutrichat")

Timezone `Europe/Oslo`, `enable_utc=False`. Each task runs its async body with
`asyncio.run` and disposes the engine afterward.

| Beat | Task |
|---|---|
| 01:15 | `aggregate_daily_summary` |
| 01:30 | `build_nutrient_checkup` |
| 07:00 | `send_daily_summary_telegram` |
| Sun 23:00 | `build_weekly_summary` |
| Sun 23:20 | `dispatch_log_habits` → one rate-limited `infer_log_habits` per eligible user |
| on demand | `embed_meal_summary`, `extract_and_store_facts` |

Worker runs `--concurrency=${CELERY_CONCURRENCY:-2} --without-gossip --without-mingle`
(Railway reports 48 CPUs; defaults OOM).

## 7. Telegram (`telegram/`)

aiogram 3, plain-text replies. Handlers: `/start /help /link /new /goals /progress`,
photo + text messages, inline callbacks `q:` (quantity), `sw:` (swap candidate),
`pk:` (picker), `ok`/`no`. The bot calls `handle_message` **in-process** — no HTTP
hop — and holds its own checkpointer pool in polling mode. Webhook mode verifies
`X-Telegram-Bot-Api-Secret-Token`.

## 8. Frontend (`frontend/`)

Vite · React 19 · TS · Tailwind 4 · TanStack Query 5 · Zustand 5 · react-router 7 · recharts.

Routes: `/login`, `/auth/callback` (public); protected: `/onboarding /chat /my-meals
/trends /settings /upgrade`; `/` and `*` → `/chat`.

- `api/client.ts` — base `VITE_API_URL`; fetches a fresh Supabase token per request;
  on 401 one `refreshSession()` retry then `signOut()`.
- `api/hooks.ts` — query keys `['dashboard','today']`, `['trends',days]`, `['goals']`,
  `['my-meals']`, `['nutrient-checkup']`, `['quota']`, `['telegram','link']`, `['mindful-today']`.
- Stores: `authStore` (session, dev bypass), `mealStore` (chat + confirmation card), `mascotStore`.
- Auth: Supabase implicit flow; `AuthCallbackPage` reads `#access_token`.
- Push: `lib/push.ts` registers `/sw.js`, posts subscription to `/push/subscribe`
  (sender not yet implemented).

## 9. Observability (`observability.py`)

Logfire (OTel), service `nutrichat`, `LOGFIRE_ENABLED=false` disables everything.
Instruments FastAPI, asyncpg, redis, celery, aiohttp, httpx, LangChain, Pydantic AI.
Key spans: `handle_message`, `meal_logging`, `coaching`, `classify_intent_llm`,
`telegram_update`. Logs: `quota_*`, `ratelimit_*`, `llm_cost`. Scrubber redacts
image base64.

## 10. Eval

- `eval/run_eval.py` — USDA Recall@1 and false-fallback rate on `test_set_200.jsonl`.
- `eval/gate.py` — regression gate for latency/prompt changes; categories
  `entity_recall, quantity, food_identity, intent_routing, decomposition_kcal_pct`
  with tolerances; baseline `eval/baseline_scores.json`.
  `uv run --env-file .env python eval/gate.py --runs 5 --baseline eval/baseline_scores.json`

## 11. Configuration

Root `.env`: `GOOGLE_API_KEY DATABASE_URL REDIS_URL SUPABASE_URL SUPABASE_ANON_KEY
SUPABASE_JWT_SECRET USDA_API_KEY LOGFIRE_* TELEGRAM_* VAPID_* DEV_BYPASS_AUTH`.
Used in code but missing from `.env.example`: `FRONTEND_ORIGIN RATE_LIMIT_IP_PER_MIN
PROC PORT CELERY_CONCURRENCY USDA_DB_PATH NUTRICHAT_TUNABLES_PATH`.
Frontend: `VITE_API_URL VITE_SUPABASE_URL VITE_SUPABASE_ANON_KEY VITE_APP_URL`.

## 12. Key design decisions

1. **Interrupt-before-write.** The graph pauses after `present`; the user's confirmation resumes it. Nothing hits `meal_log` unconfirmed.
2. **Local USDA first.** Bundled SQLite FTS5 replaces the unreliable FDC API; cache + LLM estimate are the tail.
3. **Postgres is truth, Redis is a hint.** Today's totals are always computed from `meal_log` (`get_today_totals`); Redis holds no copy of them.
4. **One image, three roles.** `PROC` switch keeps deploys simple; Telegram in prod rides the web process.
5. **Keyword prefilter before LLM intent.** Cheap, deterministic routing for obvious cases; the LLM only breaks ties.
6. **Two agent frameworks on purpose.** LangGraph for the stateful, interruptible logging flow; Pydantic AI for coaching, which keeps its own short Redis conversation memory instead of sharing the LangGraph checkpoint (pedagogical comparison).

## 13. Known gaps

- No cross-provider LLM fallback despite the CLAUDE.md claim (Claude Haiku unused).
- Push sender not implemented (subscriptions collected only).
- Migrations are manual in prod.
- `.env.example` drift (see §11).
