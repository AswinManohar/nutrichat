# Mealsy

Log a meal in one sentence. Mealsy turns "had two eggs and toast this morning" into
USDA-grounded nutrition data, tracks it against your daily goals, and coaches you
from your own history.

> Formerly **NutriChat**. The repo and some infrastructure identifiers keep the old name.

---

## Project goal

**Product goal.** Make food tracking light enough that people keep doing it. No forms,
no calorie-obsessed grids, no red warning numbers: you describe what you ate, confirm
the card, and move on. Numbers inform; they never judge.

**Learning goal.** Mealsy is also a hands-on project for building *robust* agentic
systems, the kind that hold up with real users rather than in a demo. It works
through patterns such as:

- **Human-in-the-loop state machines.** The logging graph pauses for confirmation and
  correction (LangGraph interrupts and a Postgres checkpointer).
- **Typed routing judgments.** TypeSafe Jev decides between logging and coaching, with
  a Gemini classifier as a safety net.
- **Layered fallbacks.** Food lookup goes from the bundled USDA database to the FDC API
  to an LLM estimate, so a flaky upstream never blocks a log.
- **Grounded generation.** Coaching draws on the user's logged history and a curated,
  condition-filtered dietary-guideline corpus (pgvector).
- **Evals as gates.** An offline and live eval harness, plus per-capability gates
  checked against stored baselines.
- **Observability.** End-to-end traces with Logfire (OpenTelemetry).

---

## Features

- **Natural-language and photo meal logging** with an editable confirmation card
  (per-ingredient breakdown, quantity fixes, "replace X with Y").
- **Saved meals** that you can re-log in one tap, with an offer to update a saved
  recipe when you change it.
- **Daily goals, totals and trends** for macros and micronutrients.
- **Coaching**: questions like "how am I doing on protein?", meal plans for your
  remaining goals, and proactive daily and weekly summaries and nutrient check-ups.
- **Multiple clients**: a React web app, a native Android app, and a Telegram bot.
- **Integrations API** (`/v1/integrations`, scoped API keys) for reading meals and
  summaries from other tools. See [docs/integration-api.md](docs/integration-api.md).
- **Notifications** through web push (VAPID) and Android push (FCM).

---

## How it works

```
 Web (React)  ─┐
 Android      ─┼─ JWT ─▶  FastAPI ──▶ Orchestrator
 Telegram     ─┘                        │
                                        ├─ paused thread? ─▶ resume logging graph
                                        │
                                        └─ Jev router (Gemini safety net)
                                              │                 │
                                         log_meal           coaching
                                              ▼                 ▼
                              LangGraph logging graph     Pydantic AI coaching agent
                              extract (Gemini 2.5 Flash)  history + guideline RAG
                              → USDA resolve                    │
                                (SQLite → FDC API → LLM)        │
                              → interrupt: confirm/correct      │
                              → write meal_log                  │
                                              ▼                 ▼
                        Postgres 16 + pgvector (Supabase) · Redis totals cache
                                              ▲
                        Celery beat: daily/weekly summaries, check-ups, digests
```

For the full picture (routes, graph nodes, data model, workers) see
[docs/architecture.md](docs/architecture.md). For how foods are matched against USDA
data, see [docs/usda-matching-methods.md](docs/usda-matching-methods.md).

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13 · FastAPI (async) · SQLAlchemy 2 (asyncpg) · Alembic · `uv` |
| Agents | LangGraph (meal logging, Postgres checkpointer) · Pydantic AI (coaching) |
| Intent routing | TypeSafe Jev (System One), with a Gemini classifier as the safety net |
| LLM | Gemini 2.5 Flash (extraction and coaching; extraction runs with thinking disabled) |
| Embeddings | `gemini-embedding-001` (768-dim) |
| Database | PostgreSQL 16 + pgvector (Supabase in production) |
| Cache / broker | Redis |
| Background jobs | Celery + Celery beat |
| Food data | USDA FoodData Central (bundled SQLite and the FDC API) |
| Auth | Supabase Auth (ES256 JWTs verified through JWKS) |
| Web frontend | React 19 · TypeScript · Vite · Tailwind CSS 4 · TanStack Query · Zustand |
| Android | Kotlin · Jetpack Compose · Hilt · Retrofit · Room · supabase-kt |
| Telegram bot | aiogram 3 (polling in dev, webhook in production) |
| Observability | Logfire (OpenTelemetry) |
| Hosting | Railway (web / worker / bot + Redis) · Netlify (web) · Supabase (Postgres, Auth) |

---

## Repository layout

```
nutrichat/
├── src/backend/
│   ├── agent/          # orchestrator, LangGraph graph, Jev router, coaching, tools/
│   ├── api/            # FastAPI routers (meals, goals, my-meals, coaching, push, ...)
│   ├── auth/           # Supabase JWT + integration API-key auth
│   ├── db/             # SQLAlchemy models, Redis client, Alembic migrations
│   ├── guidelines/     # dietary-guideline corpus: chunking, ingest, retrieval
│   ├── telegram/       # aiogram bot
│   ├── workers/        # Celery tasks
│   └── main.py         # FastAPI app
├── frontend/           # React web app
├── android/            # native Android app (see android/README.md)
├── eval/               # eval harness, datasets, baselines, gates
├── docs/               # architecture, deployment, design notes
├── specs/              # feature specs (spec-driven development)
├── supabase/           # Supabase config
└── scripts/            # run-local.sh, deploy helpers
```

---

## Getting started

### Prerequisites

- Python 3.13+ and [`uv`](https://docs.astral.sh/uv/)
- Node.js 18+ and npm
- Docker (for local Postgres + pgvector and Redis)
- A Supabase project for auth. Auth is always enforced; there is no dev bypass.

### 1. Configure the environment

```bash
cp .env.example .env
```

| Variable | Required | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | yes | Gemini models and embeddings |
| `DATABASE_URL` | yes | Postgres connection string |
| `REDIS_URL` | yes | Redis connection string |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | yes | Auth (JWT verification through JWKS) |
| `USDA_API_KEY` | recommended | FDC API fallback ([sign up](https://fdc.nal.usda.gov/api-key-signup/)) |
| `TYPESAFE_API_KEY` | optional | Jev intent routing. If unset, Gemini routes everything. |
| `LOGFIRE_TOKEN` | optional | Tracing |
| `TELEGRAM_BOT_TOKEN` | optional | Telegram bot |

See `.env.example` for the full list (push keys, Firebase, billing flags, and more).

### 2. Start Postgres and Redis

```bash
docker compose up -d
```

### 3. Run migrations

```bash
uv sync
PYTHONPATH=src uv run alembic upgrade head
```

### 4. Seed data (optional)

```bash
# 30 days of eating history for a debug user
PYTHONPATH=src uv run python src/backend/scripts/seed_debug_user.py

# Embed the dietary-guideline corpus used by coaching
PYTHONPATH=src uv run python -m backend.guidelines.ingest --dir docs/guidelines
```

### 5. Run

```bash
bash scripts/run-local.sh                 # backend + frontend + Redis
bash scripts/run-local.sh --worker --bot  # also start the Celery worker and Telegram bot
```

- Web app: http://localhost:5173/chat
- API docs: http://localhost:8000/docs
- Logs: `logs/*.log` (for example `tail -f logs/web.log`)

For the Android app, see [android/README.md](android/README.md).

---

## Testing and evaluation

```bash
uv run pytest                     # backend tests
cd frontend && npm test           # frontend tests (Vitest)
uv run ruff check src/ --fix      # lint

# Agent evals
python eval/run_eval.py --dataset eval/test_set_200.jsonl --mock   # offline
python eval/run_eval.py --dataset eval/test_set_200.jsonl          # live
python eval/gate.py --only intent_routing --runs 5 \
    --baseline eval/baseline_intent_legacy.json                    # routing gate
```

---

## Deployment

The backend ships as a single image deployed as three Railway services (`PROC=web`,
`worker` and `bot`, dispatched by `start.sh`). The web app is hosted on Netlify, and
Postgres and Auth on Supabase. Migrations are applied manually.

- [docs/deployment/deploy-guide.md](docs/deployment/deploy-guide.md)
- [docs/deployment/railway.md](docs/deployment/railway.md)
- [docs/deployment/netlify.md](docs/deployment/netlify.md)

---

## Further reading

- [docs/architecture.md](docs/architecture.md): system architecture
- [docs/usda-matching-methods.md](docs/usda-matching-methods.md): how food names map to USDA entries
- [docs/telegram-bot.md](docs/telegram-bot.md): Telegram bot
- [docs/observability.md](docs/observability.md): Logfire tracing
- [docs/coaching-meal-plans.md](docs/coaching-meal-plans.md): coaching meal plans

---

## Data

Nutrition data comes from [USDA FoodData Central](https://fdc.nal.usda.gov/), which is
public domain (CC0).
