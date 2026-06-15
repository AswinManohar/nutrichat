# 🥗 NutriChat

NutriChat is an agentic nutrition tracking platform that lets users log meals in natural language, automatically lookup nutrients from the USDA database with AI fallbacks, and get personalized, data-grounded coaching.

---

## 🛠️ Tech Stack

- **Backend:** Python 3.12 · FastAPI · SQLAlchemy
- **Agent Engines:**
  - **Meal Logging:** LangGraph (interrupt-based state machine for user confirmation/corrections)
  - **AI Coaching:** Pydantic AI (proactive coaching grounded in database history)
- **Database & Cache:** PostgreSQL 16 + `pgvector` · Redis (caching today's totals + Celery broker)
- **Background Workers:** Celery (macro/micro daily summaries, weekly aggregates, vectorization)
- **LLMs & APIs:** Gemini APIs (`gemini-2.5-flash`, `gemini-3.1-flash-lite` for extraction/embeddings) · USDA FoodData Central API
- **Frontend:** React 19 · TypeScript · Vite · Tailwind CSS
- **Telegram Client:** `aiogram 3` (polling for local dev, webhooks in production)
- **Observability:** Logfire (OpenTelemetry instrumentation)

---

## 🚀 Getting Started

### 📋 Prerequisites
- Python 3.12+ (recommend using `uv` for package management)
- Node.js 18+ & npm
- Docker (for starting local Postgres/Redis containers)

---

### ⚙️ Setup Instructions

#### 1. Clone & Environment Configuration
Copy the template `.env.example` file to `.env`:
```bash
cp .env.example .env
```
Open `.env` and fill in the required API keys:
- `GOOGLE_API_KEY`: Gemini models and embedding API.
- `USDA_API_KEY`: USDA FoodData Central lookups.
- `DATABASE_URL`: Connection string (PostgreSQL).
- `REDIS_URL`: Connection string (Redis).
- `DEV_BYPASS_AUTH=true`: Bypasses Supabase Auth in local dev (authenticates with developer header).

#### 2. Start Database & Cache (Docker)
Ensure your Docker daemon is running, then spin up the local services:
```bash
docker compose up -d
```

#### 3. Run Database Migrations
Apply database schema migrations using Alembic:
```bash
PYTHONPATH=src uv run alembic upgrade head
```

#### 4. Seed Test Data (Optional)
To instantly populate your local dashboard with 30 days of eating history for testing:
```bash
PYTHONPATH=src .venv/bin/python src/backend/scripts/seed_debug_user.py
```

---

### 💻 Running Locally

You can launch all services (Backend, Frontend, Redis) in one command using the helper script:

```bash
# Basic run (Backend + Frontend + Redis)
bash scripts/run-local.sh

# Run with background Celery worker and Telegram bot polling active:
bash scripts/run-local.sh --worker --bot
```

Once running:
- **Frontend:** [http://localhost:5173/chat](http://localhost:5173/chat) (in bypass mode, it will auto-login as developer)
- **Backend API:** [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger documentation)
- **Logs:** Available at `logs/*.log` (e.g., `tail -f logs/web.log`)

---

### 🧪 Running Tests & Code Quality
```bash
# Run pytest test suite
uv run pytest

# Format python files
black src/

# Lint python files
ruff check src/ --fix
```
