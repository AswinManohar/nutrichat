<div align="center">
  <h1>Mealsy</h1>
  <h3>Calorie and nutrient tracking that learns your eating habits and coaches you on them.</h3>
</div>

<div align="center">
  <img src="https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white" alt="Python 3.13">
  <img src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/LangGraph-agent-1C3C3C?logo=langchain&logoColor=white" alt="LangGraph">
  <img src="https://img.shields.io/badge/Gemini-2.5%20Flash-4285F4?logo=googlegemini&logoColor=white" alt="Gemini 2.5 Flash">
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React 19">
  <a href="https://github.com/AswinManohar/nutrichat/actions/workflows/android.yml"><img src="https://github.com/AswinManohar/nutrichat/actions/workflows/android.yml/badge.svg" alt="Android CI"></a>
</div>

<br>

Mealsy is a nutrition app that tracks calories, macronutrients and micronutrients,
adapts to each user, and provides personalized coaching based on their eating habits.
Users log a meal by describing it, for example *"two eggs and toast for breakfast"*.
Mealsy identifies each food, resolves it against
[USDA FoodData Central](https://fdc.nal.usda.gov/), and records it after the user
confirms. Over time it learns the user's preferences and patterns, and uses them to
give coaching, meal plans and summaries tailored to that person.

The application runs on web, Android and Telegram.

```bash
docker compose up -d && PYTHONPATH=src uv run alembic upgrade head
bash scripts/run-local.sh
```

> [!NOTE]
> The project was previously named NutriChat. The repository and some infrastructure
> identifiers retain the original name.

## Why Mealsy?

- **Logging in one message**: describe a meal in plain language or send a photo.
  Mealsy breaks it into ingredients and portions, and the user confirms or corrects
  the result before it is saved.
- **Accurate nutrient data**: foods are matched to USDA FoodData Central, covering
  calories, macronutrients and micronutrients.
- **Adapts to the user**: Mealsy learns lasting preferences from conversations, keeps
  saved meals for one-step re-logging, and tracks each user's own goals.
- **Personalized coaching**: coaching draws on the user's logged meals, trends and
  health context, plus a curated dietary-guideline corpus. It answers questions,
  plans meals for the remaining daily goals, and sends daily and weekly summaries
  and nutrient check-ups.
- **Available where users are**: web, Android and Telegram share one account and one
  history.
- **Informative, not judgmental**: intake is shown as information. Going over a goal
  is not presented as a failure.

## Integrations

- [Telegram bot](docs/telegram-bot.md) linked to the same account
- Read-only [integrations API](docs/integration-api.md) with scoped API keys
- Web push (VAPID) and Android push (FCM) notifications

## Architecture

```
 Web (React)  ─┐
 Android      ─┼─ JWT ─▶  FastAPI ──▶ Orchestrator
 Telegram     ─┘                        │
                                        ├─ paused thread? ─▶ resume logging graph
                                        │
                                        └─ GLiDE router (Gemini safety net)
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

### Reliability

- **[Human-in-the-loop](docs/architecture.md)**: the logging graph pauses on a
  LangGraph interrupt for confirmation and corrections. State persists in a Postgres
  checkpointer, so a paused meal survives restarts.
- **Typed routing**: Fastino GLiDE classifies each message as logging or coaching. A
  Gemini classifier acts as a safety net.
- **[Layered food lookup](docs/usda-matching-methods.md)**: bundled USDA database,
  then the FDC API, then an LLM estimate, so an upstream outage does not block logging.
- **Evals as release gates**: an offline and live harness, plus per-capability gates
  compared against stored baselines.
- **[Observability](docs/observability.md)**: end-to-end Logfire (OpenTelemetry)
  traces across the API, agents, workers and external calls.

See [docs/architecture.md](docs/architecture.md) for routes, graph nodes, the data
model and background jobs.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13 · FastAPI · SQLAlchemy 2 (asyncpg) · Alembic · uv |
| Agents | LangGraph (logging) · Pydantic AI (coaching) |
| Intent routing | Fastino GLiDE, with a Gemini classifier as safety net |
| Models | Gemini 2.5 Flash · `gemini-embedding-001` (768-dim) |
| Data | PostgreSQL 16 + pgvector · Redis · USDA FoodData Central |
| Background jobs | Celery + Celery beat |
| Auth | Supabase Auth (ES256 JWTs verified through JWKS) |
| Web | React 19 · TypeScript · Vite · Tailwind CSS 4 · TanStack Query · Zustand |
| Android | Kotlin · Jetpack Compose · Hilt · Retrofit · Room · supabase-kt |
| Telegram | aiogram 3 |
| Observability | Logfire (OpenTelemetry) |
| Hosting | Railway · Netlify · Supabase |

## Getting started

**Prerequisites:** Python 3.13+, [uv](https://docs.astral.sh/uv/), Node.js 18+,
Docker, and a Supabase project for authentication.

```bash
cp .env.example .env          # set GOOGLE_API_KEY, DATABASE_URL, REDIS_URL,
                              # SUPABASE_URL, SUPABASE_ANON_KEY, USDA_API_KEY
docker compose up -d          # Postgres 16 + pgvector, Redis
uv sync
PYTHONPATH=src uv run alembic upgrade head

# Optional: seed 30 days of history and embed the guideline corpus
PYTHONPATH=src uv run python src/backend/scripts/seed_debug_user.py
PYTHONPATH=src uv run python -m backend.guidelines.ingest --dir docs/guidelines

bash scripts/run-local.sh                 # API, web app, Redis
bash scripts/run-local.sh --worker --bot  # also Celery worker and Telegram bot
```

The web app runs at `http://localhost:5173/chat` and the API docs at
`http://localhost:8000/docs`. `FASTINO_API_KEY` is optional; without it, Gemini
handles all routing. See `.env.example` for the full list of settings and
[android/README.md](android/README.md) for the Android client.

## Testing and evaluation

```bash
uv run pytest                     # backend tests
cd frontend && npm test           # web tests (Vitest)
uv run ruff check src/            # lint

python eval/run_eval.py --dataset eval/test_set_200.jsonl --mock   # offline eval
python eval/gate.py --only intent_routing --runs 5 \
    --baseline eval/baseline_intent_legacy.json                    # routing gate
```

## Documentation

- [Architecture](docs/architecture.md): system design, routes, agent graph, data model
- [USDA matching](docs/usda-matching-methods.md): how food names are resolved to USDA entries
- [Coaching meal plans](docs/coaching-meal-plans.md): goal-aware meal planning
- [Observability](docs/observability.md): Logfire tracing setup
- [Telegram bot](docs/telegram-bot.md): bot setup and account linking
- [Integrations API](docs/integration-api.md): read-only API for external tools
- [Deployment guide](docs/deployment/deploy-guide.md): Railway, Netlify and Supabase

## Acknowledgements

Nutrition data comes from [USDA FoodData Central](https://fdc.nal.usda.gov/), which is
in the public domain (CC0). Agent orchestration is built on
[LangGraph](https://github.com/langchain-ai/langgraph) and
[Pydantic AI](https://github.com/pydantic/pydantic-ai), and intent routing uses
Fastino GLiDE.
