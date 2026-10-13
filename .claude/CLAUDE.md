# CLAUDE.md — Mealsy

Mealsy is a production nutrition app (renamed from "NutriChat"; the git repo
directory is still `nutrichat/` and some infra identifiers keep the old name — see
docs/deployment/deploy-guide.md). It tracks calories, macronutrients and
micronutrients, adapts to each user, and provides personalized coaching based on
their eating habits. Users describe meals in natural language; the agent extracts
food entities, resolves them against USDA FoodData Central, and tracks them against
the user's goals. It is not a demo or learning project: treat changes as changes to
a live app with real users.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13 · FastAPI · async · SQLAlchemy 2 (asyncpg) · uv |
| Agent | LangGraph (logging, Postgres checkpointer) · Pydantic AI (coaching) |
| Observability | Logfire (OpenTelemetry) |
| LLM — extraction | Gemini 3.1 Flash-Lite (thinking disabled — see tunables `extraction_thinking_budget`) |
| LLM — coaching | Gemini 3.1 Flash-Lite |
| Typed judgments | Fastino GLiDE (System One): log/coaching intent routing with Gemini classifier as safety net; memory save decision |
| Database | PostgreSQL 16 + pgvector |
| Cache | Redis |
| Task queue | Celery + Redis |
| Embeddings | Gemini gemini-embedding-001 (768-dim via output_dimensionality) |
| Auth | Supabase Auth (ES256 JWTs via JWKS; no dev bypass) |
| Frontend | React 19 · TypeScript · Vite · Tailwind CSS 4 · TanStack Query · Zustand |
| Android | Kotlin · Jetpack Compose · Hilt · Retrofit · Room · supabase-kt (see android/CLAUDE.md) |
| Telegram bot | aiogram 3 (polling for dev, webhook for prod) |
| Food data | USDA FoodData Central (CC0): bundled SQLite → FDC API → LLM estimate |
| Hosting | Railway (backend: web/worker/bot + Redis) · Netlify (frontend) · Supabase (Postgres) |

---

## Project layout

Folders are suggested, not locked. Add or rename as the project evolves.
Update this file when the layout changes significantly.

```
nutrichat/
├── src/backend/                # Python package `backend` (run with PYTHONPATH=src)
│   ├── agent/
│   │   ├── context.py          # build_context(), build_system_prompt()
│   │   ├── graph.py            # LangGraph StateGraph (logging)
│   │   ├── orchestrator.py     # handle_message(), _route() decision rule
│   │   ├── glide.py            # Fastino GLiDE client (typed judgments)
│   │   ├── system_one.py       # GLiDE routing judgment (judge_message)
│   │   ├── coaching.py         # Pydantic AI coaching agent
│   │   ├── coaching_store.py   # persist each coaching turn for feedback/eval
│   │   ├── memory.py           # preference profile: apply_ops write rules, render
│   │   ├── memory_curator.py   # background curators (per turn, weekly from logs)
│   │   ├── memory_judge.py     # GLiDE scores curator candidates; threshold decides
│   │   ├── memory_tools.py     # coach tools: remember, forget, set_diet
│   │   ├── llm.py · cost.py    # model clients, token cost accounting
│   │   └── tools/
│   │       ├── meals.py        # extract_entities, log_meal
│   │       ├── usda.py         # usda_lookup_batch (parallel)
│   │       ├── usda_local.py   # bundled USDA SQLite lookup
│   │       ├── usda_match.py   # lexical ranker (_rank_key)
│   │       ├── decompose.py    # recipe -> ingredients
│   │       ├── replace_ingredient.py
│   │       ├── saved_meals.py
│   │       └── history.py      # get_history hybrid search
│   ├── api/                    # FastAPI routers: meals, goals, my_meals, foods,
│   │                           # coaching_feedback, memory, nutrient_checkup, mindful, quota,
│   │                           # billing, push, devices, telegram_link, integrations
│   ├── auth/                   # supabase.py (JWT/JWKS), integration.py (API keys)
│   ├── config/                 # tunables.yaml, prompts/
│   ├── core/                   # nutrition_day.py (day boundaries)
│   ├── guidelines/             # curated dietary-guideline corpus
│   │   ├── chunking.py         # markdown + frontmatter -> Chunk
│   │   ├── ingest.py           # idempotent embed + sync CLI
│   │   ├── retrieval.py        # condition-filtered pgvector search
│   │   └── export_feedback.py  # rated coaching turns -> JSONL
│   ├── db/
│   │   ├── models.py           # SQLAlchemy ORM
│   │   ├── session.py          # async engine/session
│   │   ├── checkpointer.py     # LangGraph Postgres checkpointer pool
│   │   ├── redis_client.py     # connection pool + helpers
│   │   └── migrations/versions/
│   ├── push/                   # FCM sender
│   ├── telegram/               # aiogram bot
│   ├── workers/tasks.py        # Celery tasks + beat schedule
│   └── main.py                 # FastAPI app
├── frontend/src/               # api/, components/, hooks/, lib/, pages/, stores/ (Zustand)
├── android/                    # native app (own CLAUDE.md and README.md)
├── tests/                      # pytest suite
├── eval/                       # run_eval.py, gate.py, cases/, baselines
├── specs/                      # spec-kit feature specs (NNN-name/)
├── supabase/                   # Supabase config
├── scripts/                    # run-local.sh, deploy helpers
└── docs/                       # architecture.md, deployment/, guidelines/
```

---

## Environment variables

```bash
GOOGLE_API_KEY=          # Gemini 3.1 Flash-Lite + embeddings
ANTHROPIC_API_KEY=       # reserved; not used by current code
FASTINO_API_KEY=         # GLiDE judgments (routing, memory); unset = Gemini routes everything
DATABASE_URL=            # postgresql://...
REDIS_URL=               # redis://...
SUPABASE_URL=            # https://xxx.supabase.co
SUPABASE_ANON_KEY=       # eyJ...
USDA_API_KEY=            # fdc.nal.usda.gov/api-key-signup/
# Full list (Logfire, Telegram, VAPID, Firebase, billing flags): .env.example
```

---

## Commands

```bash
# Everything at once (API + frontend + Redis; optional worker and bot)
bash scripts/run-local.sh [--worker] [--bot]

# Backend
docker compose up -d                       # Postgres 16 + pgvector, Redis
PYTHONPATH=src uv run alembic upgrade head
uv run uvicorn backend.main:app --reload --port 8000 --app-dir src
PYTHONPATH=src uv run celery -A backend.workers.tasks worker --loglevel=info
PYTHONPATH=src uv run python -m backend.telegram.bot   # polling mode (dev)
uv run pytest                              # DB tests need DATABASE_URL

# Ship to production (checks → promote → deploy); see deploy-guide.md
scripts/push-to-production.sh --dry-run    # or /ship in Claude Code

# Guidelines corpus
PYTHONPATH=src python -m backend.guidelines.ingest --dir docs/guidelines [--dry-run]
PYTHONPATH=src python -m backend.guidelines.export_feedback \
    [--rated-only] [--since YYYY-MM-DD] --out eval/coaching_feedback.jsonl

# Frontend
cd frontend && npm run dev
cd frontend && npm test          # Vitest

# Eval
python eval/run_eval.py --dataset eval/test_set_200.jsonl --mock  # offline
python eval/run_eval.py --dataset eval/test_set_200.jsonl          # live
python eval/gate.py --only intent_routing --runs 5 \
    --baseline eval/baseline_intent_legacy.json                   # routing gate
python eval/probe_glide.py --check | --scores | --n 50          # GLiDE: request, thresholds, latency
PYTHONPATH=src python eval/eval_profile_curator.py --runs 3      # memory curator
PYTHONPATH=src python eval/eval_profile_coaching.py --runs 3     # restrictions gate
```

---

## Debugging workflow

### On the phone (preferred): Pixel 9 over wireless adb

The phone is already paired. When Wireless debugging is on, it advertises
itself over mDNS, so you don't need to ask for an IP or port.

```bash
ADB=~/Android/Sdk/platform-tools/adb
$ADB mdns services && $ADB devices -l      # should list "Pixel_9 … device"
$ADB reverse tcp:8000 tcp:8000             # app → laptop backend at localhost:8000
docker start nutrichat-redis               # backend needs local Redis
PYTHONPATH=src uv run --env-file .env uvicorn backend.main:app \
    --host 127.0.0.1 --port 8000           # code doesn't load .env itself
curl -s localhost:8000/meta/app            # health check, expect 200
cd android && ./gradlew :app:assembleDebug
$ADB install -r android/app/build/outputs/apk/debug/app-debug.apk
$ADB shell monkey -p app.mealsy.android -c android.intent.category.LAUNCHER 1
$ADB logcat --pid=$($ADB shell pidof app.mealsy.android)   # app logs
```

- Repair only if `mdns services` is empty: Wireless debugging → *Pair device
  with pairing code* → `adb pair IP:pairport CODE`, then `adb connect IP:port`.
- `adb reverse` is lost whenever the phone reconnects. Re-run it if the app
  shows network errors.
- `android/local.properties` holds `API_BASE_URL=http://localhost:8000`. It
  works for the phone and the emulator alike through `adb reverse`.

### Emulator (fallback)

AVD `Medium_Phone_API_36`. Launch with
`emulator -avd Medium_Phone_API_36 -memory 2048 -gpu swiftshader_indirect
-feature -Vulkan`. Without these flags it hangs on a grey screen. The host
has ~14 GB of RAM and the emulator gets OOM-killed, so ask before launching
it. Booting from a snapshot can bring back an old APK, so reinstall the APK
after every boot.

### Things that bite

- **The local backend writes to the production Supabase database** (the
  `DATABASE_URL` in `.env`). Anything you log while testing is real user
  data. Run the backend from the branch that matches production's schema; a
  feature branch with new migrations or a new data format must not point at
  prod.
- **Gemini key and spend cap.** The Google project behind `GOOGLE_API_KEY`
  was replaced on 2026-10-13 after the old one hit its cap; new projects are
  not offered `gemini-2.5-flash`. When a project's monthly spend cap is hit,
  every Gemini call returns HTTP 429 "exceeded its monthly spending cap", so
  extraction, estimates and coaching all fail. Check the backend log before
  debugging the app (issue #59).
- One Gradle run at a time per checkout. Don't wrap builds in `pgrep` guards,
  because they livelock.
- `test_e2e_meals.py::test_chat_history_isolation` always fails offline (it
  calls real Gemini).

### Backend tests against a local database

DB-backed tests skip unless `DATABASE_URL` is set. Use a throwaway database
on the docker Postgres (`docker start nutrichat-pg`, port 5411). Before
`alembic upgrade head`, run `CREATE EXTENSION vector; CREATE SCHEMA auth;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS 'select
null::uuid';` because migration 017's RLS policies call Supabase's
`auth.uid()`. Then run
`DATABASE_URL=postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/<db>
uv run pytest`. Never point tests at the production `DATABASE_URL`.

---

## Python coding standards

Based on [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
and [PEP 8](https://peps.python.org/pep-0008/).

### Naming

```python
# Modules and packages — short, lowercase, underscores only if needed
import redis_client

# Functions and variables — snake_case
def build_system_prompt(ctx: ContextBundle) -> str: ...
today_totals = get_today_totals(user_id)

# Classes — PascalCase
class ContextBundle:
class FoodEntity(BaseModel):

# Constants — UPPER_SNAKE_CASE at module level
MAX_ITERATIONS = 5
USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"

# Private helpers — leading underscore
def _score_match(query: str, result: str) -> float: ...

# Type aliases — PascalCase
EntityList = list[FoodEntity]
```

### Type annotations

All functions must have type annotations. Use `from __future__ import annotations`
at the top of every file to avoid circular import issues with forward references.

```python
from __future__ import annotations
from typing import Optional

# Always annotate — no bare dicts or lists in function signatures
def handle_message(
    user_id: str,
    user_input: str,
    history: list[BaseMessage],
) -> str: ...

# Optional fields — use Optional[T] or T | None (Python 3.10+)
disambiguation_hint: Optional[str] = None

# Return None explicitly when a function can return nothing
def reset_day_key(user_id: str) -> None: ...
```

### Docstrings — Google style

```python
def usda_lookup_batch(entities: list[dict]) -> list[dict]:
    """Fetch USDA nutrients for multiple food entities in parallel.

    Checks Postgres cache first. Falls back to FDC API on miss
    and writes the result back to cache.

    Args:
        entities: List of dicts with keys food_name (str) and qty_g (float).

    Returns:
        List of dicts with fdc_id, food_name, qty_g, kcal, protein_g,
        carbs_g, fat_g, fiber_g, match_confidence, and optional candidates.

    Raises:
        aiohttp.ClientError: If the FDC API is unreachable after retries.
    """
```

One-liners are fine for simple private helpers:

```python
def _to_lower(s: str) -> str:
    """Return lowercased string for case-insensitive comparison."""
    return s.lower().strip()
```

### Imports

```python
# Order: stdlib → third-party → local. One blank line between groups.
from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

import aiohttp
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

from backend.db.redis_client import get_today_totals
from backend.db.models import MealLog
```

Never use wildcard imports (`from module import *`). Never import inside
function bodies unless avoiding a circular import — document why if you do.

### Error handling

```python
# Be specific — never bare except
try:
    result = await fdc_api.search(food_name)
except aiohttp.ClientTimeout:
    logger.warning("FDC timeout for %s, returning cache miss", food_name)
    return {"error": "timeout", "food_name": food_name}
except aiohttp.ClientError as exc:
    logger.error("FDC request failed: %s", exc)
    raise

# Use custom exceptions for domain errors
class ClarificationRequired(Exception):
    """Raised when an entity cannot be logged without user confirmation."""

    def __init__(self, unresolved: list[dict]) -> None:
        self.unresolved = unresolved
        super().__init__(f"{len(unresolved)} entities need clarification")
```

### Async

All I/O must be async. Never call blocking functions from async code.

```python
# Correct — parallel I/O with asyncio.gather
async def _lookup_all(entities: list[dict]) -> list[dict]:
    async with aiohttp.ClientSession() as session:
        return await asyncio.gather(
            *[_lookup_one(session, e["food_name"], e["qty_g"]) for e in entities]
        )

# Wrong — sequential in async context
async def _lookup_all_slow(entities):
    results = []
    for e in entities:
        results.append(await _lookup_one(e))  # blocks loop unnecessarily
    return results

# Wrong — blocking call in async context
async def bad():
    time.sleep(1)        # blocks event loop — use asyncio.sleep(1)
    requests.get(url)    # use aiohttp instead
```

### Pydantic models

Use Pydantic for all data that crosses a boundary (tool input/output, API
request/response, database row). Do not use raw dicts for structured data.

```python
from pydantic import BaseModel, Field

class FoodEntity(BaseModel):
    food_name: str = Field(description="USDA-style name, specific")
    qty_g: float   = Field(gt=0, description="Gram weight")
    confidence: float = Field(ge=0.0, le=1.0)
    disambiguation_hint: Optional[str] = None

    class Config:
        # Reject unknown fields — catches bugs early
        extra = "forbid"
```

### Line length and formatting

Max line length: **88 characters**. Use Ruff for linting and formatting, and run
it only on the files you touch. Do not run Black: it is not installed in the venv,
and `uvx black` disagrees with Ruff on existing files.

```bash
uv run ruff check src/backend/path/to/file.py --fix
uv run ruff format src/backend/path/to/file.py
```

---

## TypeScript coding standards

Based on [Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html)
and the [TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/).

### Naming

```typescript
// Files — kebab-case
// confirmation-card.tsx, meal-store.ts, use-meal-log.ts

// Components — PascalCase
export function ConfirmationCard({ meal }: ConfirmationCardProps) {}

// Functions and variables — camelCase
const todayTotals = useTodayTotals()
function buildSystemPrompt(ctx: ContextBundle): string {}

// Constants — UPPER_SNAKE_CASE for true constants, camelCase for config objects
const MAX_RETRY_COUNT = 3
const defaultQueryOptions = { staleTime: 30_000 }

// Types and interfaces — PascalCase
interface MealEntity {
  foodName: string
  qtyG: number
  confidence: number
  disambiguationHint?: string
}

type Intent = 'log_meal' | 'coaching' | 'recipe' | 'history'
```

### Type safety

Never use `any`. If a type is genuinely unknown, use `unknown` and narrow it.

```typescript
// Wrong
function parseResponse(data: any) { return data.entities }

// Correct
function parseResponse(data: unknown): MealEntity[] {
  if (!isMealResponse(data)) throw new Error('Unexpected response shape')
  return data.entities
}

// Type guard
function isMealResponse(val: unknown): val is MealResponse {
  return (
    typeof val === 'object' &&
    val !== null &&
    'entities' in val &&
    Array.isArray((val as MealResponse).entities)
  )
}
```

Use `interface` for object shapes that may be extended. Use `type` for unions,
intersections, and aliases.

```typescript
// interface — extendable object shape
interface MealEntity {
  foodName: string
  qtyG: number
}

// type — union or computed shape
type MealType = 'breakfast' | 'lunch' | 'snack' | 'dinner'
type PartialEntity = Partial<MealEntity>
```

### React components

One component per file. Props interface defined above the component.

```typescript
interface MacroRingProps {
  label: string
  current: number
  goal: number
  unit: string
  color?: string
}

export function MacroRing({
  label,
  current,
  goal,
  unit,
  color = '#1D9E75',
}: MacroRingProps) {
  const pct = Math.min(100, Math.round((current / goal) * 100))
  return (
    <div role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      {/* ... */}
    </div>
  )
}
```

Keep components focused. If a component needs more than ~120 lines, split it.
Extract data-fetching into custom hooks (`use-meal-log.ts`), not inside components.

### Hooks

```typescript
// Custom hooks — always prefix with use
export function useTodayTotals(userId: string) {
  return useQuery({
    queryKey: ['today', userId],
    queryFn: () => api.getTodayTotals(userId),
    staleTime: 10_000,
  })
}

// Avoid — data fetching inside component
export function Dashboard() {
  const [data, setData] = useState(null)
  useEffect(() => { fetch('/api/today').then(...) }, []) // extract this
}
```

### Async and error handling

```typescript
// Prefer async/await over promise chains
async function logMeal(input: LogMealInput): Promise<MealLogResult> {
  const response = await api.post('/meals/log', input)
  if (!response.ok) throw new ApiError(response.status, await response.text())
  return response.json() as Promise<MealLogResult>
}

// Surface errors to the user — never swallow silently
try {
  await logMeal(entities)
} catch (error) {
  if (error instanceof ApiError) {
    toast.error(`Could not log meal: ${error.message}`)
  } else {
    toast.error('Something went wrong. Try again.')
    console.error(error)
  }
}
```

### Imports

```typescript
// Order: React → third-party → local (absolute) → local (relative)
import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { api } from '@/api/client'
import type { MealEntity } from '@/types/meal'

import { MacroRing } from './macro-ring'
```

Use path aliases (`@/`) not `../../..` chains. Configure in `tsconfig.json`:

```json
{
  "compilerOptions": {
    "paths": { "@/*": ["./src/*"] }
  }
}
```

### Line length and formatting

Max line length: **100 characters**. Use Prettier for formatting, ESLint for
linting. Do not configure Prettier — use defaults.

```bash
npx prettier --write src/
npx eslint src/ --fix
```

---

## Decisions still to make

Things that should be decided as the project develops, not upfront:

- Error monitoring: Sentry vs structured logging to Railway
- Streaming: whether to stream LLM responses token-by-token or return complete
- Voice input: Whisper API or browser Web Speech API (Phase 2)
- Testing framework: pytest fixtures strategy as the agent grows
- State management: whether Zustand is enough or if server state via TanStack Query covers it

Add a decision record here when each is settled.
