# Mealsy — Technical Deploy Guide

How Mealsy is hosted and how to ship a change to production. Everything here is
**CLI-upload based**: neither the backend nor the frontend is connected to a Git
branch, so a deploy uploads your **local working tree** — commit first, and know
that uncommitted/untracked files in the working directory are included.

> Naming note: the product is **Mealsy**, but several infra identifiers keep the
> old "nutrichat" name (Railway project, Netlify site, service/telemetry names,
> deploy URLs). That is intentional — renaming them is a separate migration.

---

## Architecture — what runs where

| Component | Host | What it is |
|---|---|---|
| API (`web`) | **Railway** (project `nutrichat`, env `production`) | FastAPI, `uvicorn backend.main:app` |
| Worker (`worker`) | **Railway** | Celery worker (embeddings, fact extraction) |
| Telegram bot (`bot`) | **Railway** | aiogram bot (webhook in prod) |
| Redis | **Railway** | image `redis:8.2.1` |
| Frontend | **Netlify** (site `nutrichat-frontend`) | React/Vite SPA, static `dist/` |
| Postgres | **Supabase** (external) | pgvector; migrations applied manually |

- Backend public URL: `https://web-production-e3eea.up.railway.app`
- Frontend public URL: `https://nutrichat-frontend.netlify.app`
- The frontend talks to the backend over CORS; the backend allows the Netlify
  origin via the `FRONTEND_ORIGIN` env var.

`web`, `worker`, and `bot` are **one image, three services**. Each sets a `PROC`
env var (`web`/`worker`/`bot`) and `start.sh` dispatches on it (see
`railway.json` → `startCommand: bash start.sh`).

---

## Prerequisites

- **Railway CLI** at `~/.railway/bin/railway`, logged in (`railway login`).
  Already linked to project `nutrichat` / env `production`.
- **Netlify CLI** (`netlify`), logged in (`netlify login`). The `frontend/`
  folder is linked to site `nutrichat-frontend`.
- A **paid Railway plan** must be active — a deploy on an expired trial fails at
  upload with "Your trial has expired."

---

## Deploy the backend (Railway)

From the repo root:

```bash
bash scripts/deploy.sh
```

This runs `railway up --service <svc> --detach` for `web`, `bot`, and `worker`
in turn — uploading the working tree, building with NIXPACKS, and triggering a
deploy. `--detach` returns after upload; builds finish on Railway (~2–3 min).

Deploy a single service instead:

```bash
~/.railway/bin/railway up --service web --detach -m "your message"
```

**Check build/deploy status:**

```bash
railway status                 # linked service summary
railway logs --service web     # stream logs for a service
```

Each service's `latestDeployment.status` moves `BUILDING → DEPLOYING → SUCCESS`
(or `FAILED`). Verify the API is live and serving the new code:

```bash
curl -s https://web-production-e3eea.up.railway.app/openapi.json \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['info']['title'])"
# -> "Mealsy"
```

`.env` is git-ignored and does **not** ship; runtime config comes from Railway
service variables (below).

---

## Deploy the frontend (Netlify)

Vite **inlines `VITE_*` env vars at build time**, so the build must use
Netlify's configured production values — NOT your local `.env.local` (which has
no `VITE_API_URL` and would bake in `http://localhost:8000`).

From `frontend/`:

```bash
cd frontend
netlify deploy --build --prod
```

`--build` runs `npm run build` (per `netlify.toml`) with the linked site's env
vars injected; `--prod` publishes to the production URL. To be safe, ensure a
stray `.env.local` can't leak a dev value into the build — either confirm it has
no `VITE_API_URL`, or move it aside for the build:

```bash
cd frontend
mv .env.local .env.local.bak 2>/dev/null || true
netlify deploy --build --prod
mv .env.local.bak .env.local 2>/dev/null || true
```

**Verify** the live site serves the new build and points at the Railway backend:

```bash
curl -s https://nutrichat-frontend.netlify.app | grep -oiE "<title>[^<]*</title>"
# -> <title>Mealsy</title>
# and the built /assets/*.js should reference web-production-e3eea.up.railway.app,
# not localhost:8000.
```

---

## Database / migrations (Supabase)

Postgres is external (Supabase) and **not** migrated as part of a deploy — there
is deliberately no Alembic release step in `start.sh`/`Procfile`. Apply schema
changes manually before (or independently of) a code deploy:

- via the Supabase MCP tools / SQL editor, or
- `alembic upgrade head` pointed at the Supabase `DATABASE_URL`.

Migrations that only add optional performance objects (e.g. the `pg_trgm` index
in `20260708_011`) don't block a code deploy; migrations that add columns the
new code reads **must** be applied first.

---

## Environment variables

Set in each host's dashboard (or via CLI). Not committed.

**Backend (Railway — per service):**

| Var | Notes |
|---|---|
| `PROC` | `web` \| `worker` \| `bot` — selects the process in `start.sh` |
| `DATABASE_URL` | Supabase Postgres (`postgresql+asyncpg://…`, session pooler) |
| `REDIS_URL` | Railway Redis |
| `GOOGLE_API_KEY` | Gemini (extraction, coaching, embeddings) |
| `USDA_API_KEY` | FoodData Central |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET` | Auth / JWKS verification |
| `FRONTEND_ORIGIN` | Netlify origin(s) allowed by CORS (comma-separated) |
| `DEV_BYPASS_AUTH` | `true` enables the `X-Debug-User-Id` bypass — **keep `false`/unset in prod** |
| `LOGFIRE_ENABLED`, `LOGFIRE_ENVIRONMENT` | Observability |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_USE_WEBHOOK` | Bot service |
| `CELERY_CONCURRENCY` | Worker service (default 2; host CPU is high → cap to avoid OOM) |
| `ANTHROPIC_API_KEY` | Optional — Claude fallback (not currently set in prod) |

**Frontend (Netlify — build-time, `VITE_`-prefixed):**

| Var | Value |
|---|---|
| `VITE_API_URL` | `https://web-production-e3eea.up.railway.app` |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon key |

Inspect current values:

```bash
railway variables --service web      # backend
cd frontend && netlify env:list      # frontend
```

---

## Rollback

- **Railway:** redeploy a previous successful deployment from the service's
  Deployments tab (or `railway up` from an earlier checked-out commit).
- **Netlify:** in the site's Deploys tab, "Publish deploy" on a prior build, or
  `netlify rollback`.

---

## Gotchas

- **No Git auto-deploy.** Both hosts deploy the local working tree via CLI.
  Whatever branch/uncommitted state you have is what ships — commit first.
- **Working tree, not HEAD.** `railway up` and `netlify deploy` upload files on
  disk (respecting `.gitignore`), including untracked-but-not-ignored files.
- **Vite env is build-time.** Changing `VITE_API_URL` requires a **rebuild +
  redeploy** of the frontend, not just an env change.
- **Trial/billing.** An expired Railway plan fails the deploy at upload.
- **Bot poller conflict.** Only one Telegram poller per token — don't run the
  local `--bot` poller while the Railway `bot` service is up.
