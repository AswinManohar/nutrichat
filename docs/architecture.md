# Mealsy — System Architecture

Status: describes the code on `feat/android-app` as of 2026-10-13.
Everything here is derived from the source; paths are relative to `src/backend/` unless stated.

## 1. One-paragraph summary

Mealsy tracks calories, macronutrients and micronutrients and coaches each user on
their eating habits. A user describes a meal in natural language (web chat, the
Android app or Telegram, optionally with a photo). A LangGraph state machine extracts
food entities with Gemini 2.5 Flash, resolves each against a bundled USDA FoodData
Central SQLite database (falling back to an LLM estimate), pauses for user
confirmation, and writes a `meal_log` row. Today's totals are always computed from
`meal_log`. Questions ("how am I doing on protein?") go to a separate Pydantic AI
coaching agent that can cite a curated dietary-guideline corpus. Celery beat tasks
produce daily and weekly summaries, nutrient checkups, and morning digests over
Telegram and push.

## 2. Runtime topology

```
Browser (React SPA, Netlify)   ──JWT──▶ ┌──────────────────────────────┐
Android app (Compose)          ──JWT──▶ │ web   : FastAPI + uvicorn    │
Telegram (webhook in prod)     ───────▶ │ worker: Celery (2 procs)     │──▶ Redis (Railway)
Integrations (API key)         ───────▶ │ bot   : aiogram polling (dev)│      broker + result + cache
                                        └──────────────┬───────────────┘
                                                       │ psycopg / asyncpg
                                           Supabase Postgres 16 + pgvector
                                           Supabase Auth (ES256 JWKS)
External: Gemini API · TypeSafe Jev · USDA FDC API (only if local DB is off)
          Logfire · Firebase Cloud Messaging · Web Push (VAPID, subscribe only)
```

One container image (`nixpacks.toml`, Python 3.13 + uv) is deployed as three Railway
services; `railway.json` starts `start.sh`, which dispatches on `PROC=web|worker|bot`.
Prod Telegram traffic enters the **web** service at `POST /telegram/webhook` when
`TELEGRAM_USE_WEBHOOK=true`; the separate `bot` service is the dev/polling path.

Migrations are applied manually against Supabase, never at release. Production is
promoted only through `scripts/push-to-production.sh`, which runs
`scripts/prod-checks.sh` (including a check that the commit's Alembic heads match
production's `alembic_version`) before fast-forwarding `production` and deploying.
A `pre-push` hook rejects direct pushes to `production`. See
`docs/deployment/deploy-guide.md`.

## 3. Backend (FastAPI)

`main.py` — `FastAPI(title="Mealsy")`. Lifespan warns if TypeSafe is unconfigured,
starts a background `warm_up()` of the TypeSafe connection, and opens one
`pooled_checkpointer()` (psycopg pool, min 1 / max `CHECKPOINTER_POOL_SIZE`,
default 8, `SELECT 1` health check) onto `app.state.checkpointer`.

Middleware (outermost first): `CORSMiddleware(FRONTEND_ORIGIN + localhost regex)`
→ `RateLimitMiddleware` (Redis fixed window, `RATE_LIMIT_IP_PER_MIN`, default
120/min per IP, fails open if Redis is down, exempts `/health`). Per-user limits are router dependencies (`user_rate_limiter`).

| Router | Routes | Notes |
|---|---|---|
| `api/meals.py` `/meals` | `POST /log` · `GET /pending` · `POST /log-items` · `GET /log` · `GET /log/{id}` · `DELETE /log/{id}` · `GET /today` · `GET /categories` · `GET /trends` | `POST /log` is the agent entrypoint, 20/min per user; `log-items` is idempotent on `client_request_id` |
| `api/goals.py` `/goals` | `GET · POST · PUT` | |
| `api/quota.py` `/quota` | `GET` | LLM credits on `user_goal` |
| `api/billing.py` `/billing` | `POST /upgrade` | gated by `BILLING_DEV_UPGRADE_ENABLED` |
| `api/my_meals.py` `/my-meals` | CRUD · `POST /{id}/log` · ingredient resolve | saved meals, embedded |
| `api/foods.py` `/foods` | `GET /search` · `GET /{fdc_id}` | food picker for corrections; 60/min and 30/min |
| `api/coaching_feedback.py` `/coaching` | `POST /{response_id}/feedback` | thumbs up/down + comment; 60/min |
| `api/nutrient_checkup.py` `/nutrient-checkup` | `GET ""` · `GET /pending-nudge` · `POST /pending-nudge/ack` | |
| `api/mindful.py` `/mindful` | `GET /today` | intake safety checks |
| `api/telegram_link.py` `/telegram` | `POST /link-code` · `GET /link` · `DELETE /link` | |
| `api/push.py` `/push` | `GET /vapid-public-key` · `POST /subscribe` | web push subscriptions |
| `api/devices.py` `/devices` | `POST /register` · `DELETE /{token}` | Android FCM tokens |
| `api/account.py` | `DELETE /account` | account deletion |
| `api/meta.py` `/meta` | `GET /app` | Android min/latest version codes; also the health probe used locally |
| `api/integrations.py` `/v1/integrations` | `GET /meals /daily-summary /weekly-summary /goals /health` | API-key auth |

Auth: `auth/supabase.py:get_current_user_id` verifies Supabase JWTs — ES256/RS256
via JWKS (cached by `kid`), legacy HS256 via `SUPABASE_JWT_SECRET`, audience
`authenticated`. There is no development bypass. Integrations use
`auth/integration.py:get_integration_user` (hashed token against
`integration_token`). `POST /meals/log` namespaces the LangGraph thread as
`{user_id}:{conversation_id}` so one user can never resume another's conversation.

## 4. Agent layer

### 4.1 Orchestrator (`agent/orchestrator.py`)

`handle_message(user_id, user_input, thread_id, checkpointer, image_b64, meal_type, action)`

1. Start the Jev routing judgment (`system_one.judge_message`) as a task so it
   overlaps the checkpoint read.
2. If the thread has a **paused graph** (interrupted after `present`), discard the
   judgment and resume the graph — the message is a confirmation, correction or
   cancel. Resumes cost no quota. An attached image also always means meal logging.
3. Otherwise `_route` decides between `log_meal` and `coaching` (§4.2).
4. The handler that does the work spends one LLM credit (`quota.consume_llm_credit`);
   over quota returns the upgrade message. Routing itself never costs a credit.
5. After the reply: append the exchange to the short coaching history in Redis, and
   fire-and-forget `extract_and_store_facts.delay(...)` (broker errors are logged,
   never raised).

Compiled graphs are cached per checkpointer identity.

### 4.2 Intent routing (`agent/system_one.py`, spec `specs/001-jev-intent-routing`)

TypeSafe Jev returns calibrated probabilities for three fixed questions in one
request: `intent`, `reports_food`, and `needs_guidance` (recorded for comparison,
never acted on). Only the message text is sent.

| Path | Condition | Decided by |
|---|---|---|
| `judgment` | certainty ≥ `typesafe.intent_min_probability` (0.75) | Jev |
| `second_opinion_unsure` | certainty below the threshold | Gemini classifier |
| `second_opinion_unavailable` | Jev timed out (0.8 s), errored, or `TYPESAFE_API_KEY` unset | Gemini classifier |

When the route is coaching and `reports_food` ≥ `typesafe.log_offer_min_probability`
(0.7), the reply ends with an offer to log. `judge_message` never raises for service
problems. Wording changes to the questions must be re-run through the routing gate
(§10).

### 4.3 Meal-logging graph (`agent/graph.py`, LangGraph)

State (`AgentState`): messages, user id, image, entities, USDA results, meal type,
card action, saved-meal fields, decomposition snapshots, `resolved`.

```
router ─image─▶ classify ─▶ extract ─▶ auto_decompose ─▶ usda_batch ─▶ present ⏸
   └─text──▶ saved_lookup ─hit─▶ present                                  │
                  └─miss──▶ extract                                       ▼
                                                                   intent_router
             log ◀── confirm ────────────────────────────────────────────┤
             apply_correction ─▶ usda_batch                              │
             decompose / combine ─▶ usda_batch                           │
             saved_lookup (new meal) ◀───────────────────────────────────┤
             cancel ─▶ END                                                ┘
```

Compiled with `interrupt_after=["present"]`; the Postgres checkpointer persists the
paused state between requests. This is the human-in-the-loop seam: nothing is
written to `meal_log` until `log`. `auto_decompose` is a pass-through unless
`features.auto_decompose_enabled` is set (currently false). `GET /meals/pending`
lets a client recover a paused card.

### 4.4 Food resolution (`agent/tools/usda.py`, `usda_local.py`, `usda_match.py`)

```
entity ─▶ use_local_db (default) ─▶ SQLite FTS5 lookup, lexical ranker (_rank_key)
            │                         └ no match or confidence < 0.6 ─▶ LLM estimate
            └ local DB off/missing ─▶ food_source cache ─▶ FDC API (1 attempt, 4 s)
                                      └ no match or confidence < 0.6 ─▶ LLM estimate
```

The bundled DB is `data/usda_fdc.sqlite3` (~17 MB, about 13.7k foods: Foundation +
SR Legacy + FNDDS). LLM estimates are cached in `food_source` and flagged
`estimated` on the card. The FDC API returns random 404s, so the local DB is the
primary path. User corrections made through the food picker are recorded in
`food_correction` with the original phrase. The ranker is deliberately lexical; see
`docs/usda-matching-methods.md`.

### 4.5 Coaching (`agent/coaching.py`, Pydantic AI)

`CoachingAgent.handle` loads the recent history from Redis, then runs `parse_query`
(Gemini Flash, thinking off, structured `QueryParsed`) → `fetch_data` (Postgres:
`get_today_totals` for today, else `tools/history.py`) → `generate_response`
(Gemini Flash, thinking **on**). Prompts live in `config/prompts/`.

**Guideline retrieval and the feedback loop.** When `parse_query` sets
`needs_guidance`, `guidelines/retrieval.py` embeds the message and runs a
condition-filtered pgvector cosine search over `guideline_chunk` (the user's
`user_goal.conditions` map to chunk tags, always including `general`). It fetches
`retrieval.guideline_top_k` rows and drops anything scoring below
`retrieval.guideline_min_score`, so an uncovered question retrieves nothing rather
than the nearest irrelevant passage. Survivors are rendered as a numbered reference
block the model cites as `[n]`; `extract_citations` maps the numbers back to chunk
ids. Retrieval is enrichment only — any failure logs a warning and the coach answers
without citations. Every coaching turn is persisted by `agent/coaching_store.py` as
a `coaching_response` row (query, parsed query with the Jev routing record, passages
shown, citations, reply, model, trace id). Clients rate it via
`POST /coaching/{id}/feedback`, and `guidelines/export_feedback.py` exports the rows
as JSONL for a coaching eval set.

### 4.6 LLM config

`agent/llm.py` reads `config/tunables.yaml`: extraction tier `gemini-2.5-flash`
with thinking budget 0, coaching `gemini-2.5-flash`, embeddings
`gemini-embedding-001` at 768 dimensions (must match the `vector(768)` columns).
No cross-provider fallback is wired. Costs are recorded via `agent/cost.py` to
Logfire. Override the tunables file with `NUTRICHAT_TUNABLES_PATH`.

## 5. Data layer

### Postgres (Supabase, pgvector, pg_trgm) — `db/models.py`, Alembic `001…017`

| Table | Role |
|---|---|
| `user_goal` | per-user goals, conditions, tracking mode, LLM quota |
| `meal_log` | the ledger: macros, `entities` JSONB, label, `embedding vector(768)`, `client_request_id`, soft delete |
| `food_source` | USDA / LLM-estimate cache keyed by `fdc_id`, trigram index on `food_name` |
| `food_correction` | user corrections from the food picker |
| `user_meal` | "My Meals" saved recipes with embeddings |
| `user_memory` | extracted preference facts with embeddings |
| `guideline_chunk` | curated dietary-guideline corpus, embedded and condition-tagged |
| `coaching_response` | every coaching turn plus its rating |
| `daily_summary`, `weekly_summary`, `nutrient_checkup` | worker outputs |
| `telegram_link`, `integration_token`, `push_subscription`, `device_token` | channel bindings |

LangGraph checkpoints live in the same database. Row level security is enabled on
user tables with an owner policy (`auth.uid() = user_id`); `guideline_chunk` has RLS
on with no policy, so it is invisible to the Supabase REST API. The backend connects
as the table owner and is unaffected. Day boundary: `Europe/Oslo`, resetting at
01:00 (`core/nutrition_day.py`, `day.*` in tunables).

### Redis — `db/redis_client.py`

| Key | Purpose | TTL |
|---|---|---|
| `coach_history:{user_id}` | last `memory.coaching_history_turns` (6) exchanges, both intents | 12 h, refreshed on write |
| `ratelimit:{scope}:{identity}` | fixed-window counters | window |
| `tgthread:` / `tgedit:` / `tguser:` | Telegram thread, edit state, linked-user cache | short |
| `tglink:code:*` | account-link codes | short |
| Celery broker + result backend | | |

Redis holds no nutrition totals.

## 6. Workers (`workers/tasks.py`, Celery "nutrichat")

Timezone from `day.timezone`, `enable_utc=False`. Each task runs its async body in a
fresh event loop and disposes the engine afterward.

| Beat | Task |
|---|---|
| 01:15 | `aggregate_daily_summary` |
| 01:30 | `build_nutrient_checkup` |
| 07:00 | `send_daily_summary_telegram` |
| 07:00 | `send_daily_summary_push` (FCM) |
| Sun 23:00 | `build_weekly_summary` |
| on demand | `embed_meal_summary`, `extract_and_store_facts`, `send_push_fcm` |

The worker runs `--concurrency=${CELERY_CONCURRENCY:-2} --without-gossip
--without-mingle` because Railway reports 48 CPUs and the default prefork count
runs out of memory.

## 7. Telegram (`telegram/`)

aiogram 3, plain-text replies. Commands: `/start /help /link /new /goals /progress`;
photo and text messages; inline callbacks for quantity (`q:`), swap (`sw:`), back
(`bk:`), picker (`pk:`), confirm and cancel. The bot calls `handle_message`
**in-process** — no HTTP hop — with thread ids `tg:{chat_id}:{uuid}`, and holds its
own checkpointer pool in polling mode. Webhook mode verifies the Telegram secret
token header.

## 8. Web frontend (`frontend/`)

Vite · React 19 · TypeScript · Tailwind 4 · TanStack Query · Zustand · react-router.

Routes: `/login`, `/auth/callback`, `/account/delete` (public); protected:
`/onboarding /chat /my-meals /trends /settings /upgrade`; `/` and `*` → `/chat`.

- `api/client.ts` — base `VITE_API_URL`, Supabase token per request.
- `api/hooks.ts` — query keys `['dashboard','today']`, `['trends',days]`,
  `['meal-categories',days]`, `['goals']`, `['my-meals']`, `['nutrient-checkup']`,
  `['quota']`, `['telegram','link']`, `['mindful-today']`.
- Stores: `authStore`, `mealStore` (chat + confirmation card), `mascotStore`.
- Auth: Supabase implicit flow; `AuthCallbackPage` handles the redirect.
- Push: subscriptions are posted to `/push/subscribe`. No web push sender exists
  yet; only Android receives pushes (FCM).

## 9. Android app (`android/`)

Kotlin · Jetpack Compose · Hilt · Retrofit · Room · supabase-kt; package
`app.mealsy.android`. It talks to the same FastAPI routes with the same Supabase
JWTs (PKCE deep link `mealsy://auth-callback`), registers its FCM token at
`/devices/register`, and reads `/meta/app` to enforce a minimum version. The design
system and per-screen QA checklist are in `android/CLAUDE.md`; setup is in
`android/README.md`.

## 10. Observability (`observability.py`)

Logfire (OpenTelemetry), service `nutrichat`; `LOGFIRE_ENABLED=false` disables all
instrumentation. Instruments FastAPI, asyncpg, Redis, Celery, aiohttp, httpx,
LangChain and Pydantic AI. Key spans: `handle_message`, `route_message`,
`classify_intent_llm`, `meal_logging`, `coaching`, `resolve_ingredient`,
`telegram_update`. The `route_message` span carries the routing path, certainty and
Jev latency.

## 11. Eval (`eval/`)

- `run_eval.py` — USDA Recall@1 and false-fallback rate on `test_set_200.jsonl`.
- `gate.py` — regression gate with per-category tolerances: `entity_recall`,
  `quantity`, `food_identity`, `intent_routing`, `ingredient_replace`,
  `decomposition_kcal_pct`. Baselines are the `baseline_*.json` files.
- `probe_jev_latency.py` — Jev latency under concurrency.
- `eval_coaching.py`, `eval_quantity.py`, `food_identity_search.py` — focused evals.

## 12. Configuration

Root `.env` (see `.env.example` for the full list): `GOOGLE_API_KEY TYPESAFE_API_KEY
DATABASE_URL REDIS_URL SUPABASE_* USDA_API_KEY LOGFIRE_* TELEGRAM_* VAPID_*
FIREBASE_CREDENTIALS_JSON ANDROID_*_VERSION_CODE BILLING_DEV_UPGRADE_ENABLED
CHECKPOINTER_POOL_SIZE`. Read by the code but absent from `.env.example`:
`FRONTEND_ORIGIN RATE_LIMIT_IP_PER_MIN NUTRICHAT_TUNABLES_PATH`, plus the Railway
process variables `PROC PORT CELERY_CONCURRENCY`. The code does not load `.env`
itself; run with `uv run --env-file .env`.

The local `.env` points `DATABASE_URL` at the production Supabase database. Tests
and branches with unapplied migrations must use a throwaway database instead.

## 13. Key design decisions

1. **Interrupt-before-write.** The graph pauses after `present`; the user's confirmation resumes it. Nothing reaches `meal_log` unconfirmed.
2. **Local USDA first.** The bundled SQLite database replaces the unreliable FDC API; the LLM estimate is the tail and is always flagged.
3. **Postgres is the single source of truth.** Totals are computed from `meal_log` on read; Redis holds only ephemeral state (rate limits, short coaching history, Telegram session).
4. **One image, three roles.** The `PROC` switch keeps deploys simple; Telegram in production rides the web process.
5. **Calibrated judgment before generation for routing.** Jev's probability decides when it is sure; the Gemini classifier is the safety net when it is unsure or unavailable.
6. **Two agent frameworks, one per job.** LangGraph for the stateful, interruptible logging flow; Pydantic AI for coaching, a typed parse → fetch → respond pipeline that keeps only a short Redis history instead of sharing the LangGraph checkpoint.
7. **Slow work stays off the reply path.** Embeddings, fact extraction, summaries and pushes run in Celery.
8. **Production is gated.** Checks, then promotion, then deploy; migrations are applied before the code that needs them.

## 14. Known gaps

- No cross-provider LLM fallback; a Gemini outage or spend-cap 429 stops extraction, estimates and coaching.
- Web push subscriptions are collected but no web sender exists.
- Migrations are manual in production.
- `.env.example` is missing three variables (§12).
- Some infra identifiers still carry the old `nutrichat` name (Celery app, Logfire service, repo directory).
