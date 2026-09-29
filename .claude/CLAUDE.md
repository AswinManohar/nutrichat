# CLAUDE.md — Mealsy

Learning/pedagogical project for building robust agentic systems (the product
was renamed from "NutriChat"; the git repo directory is still `nutrichat/` and
some infra identifiers keep the old name — see docs/deployment/deploy-guide.md).
Users describe meals in natural language;
the agent extracts food entities, resolves them against USDA FoodData Central,
and tracks daily nutrition goals.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI · async |
| Agent | LangGraph (logging) · Pydantic AI (coaching pilot) · tool-use router pattern |
| Observability | Logfire (OpenTelemetry) |
| LLM — extraction | Gemini 2.5 Flash (thinking disabled — see tunables `extraction_thinking_budget`) |
| LLM — coaching | Gemini 2.5 Flash |
| LLM — fallback | Claude Haiku 4.5 |
| Typed judgments | TypeSafe Jev (System One): log/coaching intent routing; Gemini classifier as safety net |
| Database | PostgreSQL 16 + pgvector |
| Cache | Redis |
| Task queue | Celery + Redis |
| Embeddings | Gemini gemini-embedding-001 (768-dim via output_dimensionality) |
| Auth | Supabase Auth |
| Frontend | React 19 · TypeScript · Vite · Tailwind CSS |
| Telegram bot | aiogram 3 (polling for dev, webhook for prod) |
| Food data | USDA FoodData Central (CC0, free) |
| Hosting | Railway (backend: web/worker/bot + Redis) · Netlify (frontend) · Supabase (Postgres) |

---

## Project layout

Folders are suggested, not locked. Add or rename as the project evolves.
Update this file when the layout changes significantly.

```
nutrichat/
├── backend/
│   ├── agent/
│   │   ├── context.py          # build_context(), build_system_prompt()
│   │   ├── graph.py            # LangGraph StateGraph
│   │   ├── orchestrator.py     # handle_message(), _route() decision rule
│   │   ├── system_one.py       # TypeSafe Jev routing judgment (judge_message)
│   │   ├── coaching.py         # proactive coaching logic
│   │   ├── coaching_store.py   # persist each coaching turn for feedback/eval
│   │   └── tools/
│   │       ├── meals.py        # extract_entities, log_meal
│   │       ├── usda.py         # usda_lookup_batch (parallel)
│   │       └── history.py      # get_history hybrid search
│   ├── agents/                 # Phase 2 — specialist agents
│   │   ├── logging_agent.py
│   │   ├── coaching_agent.py
│   │   └── recipe_agent.py
│   ├── api/
│   │   ├── meals.py            # POST /meals/log
│   │   ├── goals.py            # GET/PUT /goals
│   │   ├── coaching_feedback.py  # POST /coaching/{id}/feedback
│   │   └── billing.py          # Stripe
│   ├── guidelines/             # curated dietary-guideline corpus
│   │   ├── chunking.py         # markdown + frontmatter -> Chunk
│   │   ├── ingest.py           # idempotent embed + sync CLI
│   │   ├── retrieval.py        # condition-filtered pgvector search
│   │   └── export_feedback.py  # rated coaching turns -> JSONL
│   ├── db/
│   │   ├── models.py           # SQLAlchemy ORM
│   │   ├── redis_client.py     # connection pool + helpers
│   │   └── migrations/
│   │       └── versions/
│   ├── workers/
│   │   └── tasks.py            # Celery tasks
│   └── main.py                 # FastAPI app
├── frontend/
│   └── src/
│       ├── components/
│       ├── stores/             # Zustand
│       └── api/                # TanStack Query hooks
├── eval/
│   ├── eval_harness.py
│   ├── run_eval.py
│   └── test_set_200.jsonl
└── docs/
    └── PRD.md
```

---

## Environment variables

```bash
GOOGLE_API_KEY=          # Gemini Flash-Lite + embeddings
ANTHROPIC_API_KEY=       # fallback / eval runs
TYPESAFE_API_KEY=        # Jev intent routing; unset = Gemini routes everything
DATABASE_URL=            # postgresql://...
REDIS_URL=               # redis://...
SUPABASE_URL=            # https://xxx.supabase.co
SUPABASE_ANON_KEY=       # eyJ...
USDA_API_KEY=            # fdc.nal.usda.gov/api-key-signup/
```

---

## Commands

```bash
# Backend
uvicorn backend.main:app --reload --port 8000
alembic upgrade head
celery -A backend.workers.tasks worker --loglevel=info
python -m backend.telegram.bot   # Telegram bot, polling mode (dev)

# Guidelines corpus
PYTHONPATH=src python -m backend.guidelines.ingest --dir docs/guidelines [--dry-run]
PYTHONPATH=src python -m backend.guidelines.export_feedback \
    [--rated-only] [--since YYYY-MM-DD] --out eval/coaching_feedback.jsonl

# Frontend
cd frontend && npm run dev

# Eval
python eval/run_eval.py --dataset eval/test_set_200.jsonl --mock  # offline
python eval/run_eval.py --dataset eval/test_set_200.jsonl          # live
python eval/gate.py --only intent_routing --runs 5 \
    --baseline eval/baseline_intent_legacy.json                   # routing gate
python eval/probe_jev_latency.py --n 50 --concurrency 1,5,10      # Jev latency
```

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

Max line length: **88 characters** (Black default). Use Black for formatting,
Ruff for linting. Do not configure either — use defaults.

```bash
black backend/
ruff check backend/ --fix
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
