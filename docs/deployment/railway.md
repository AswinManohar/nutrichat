# Railway deployment runbook

NutriChat backend runs as **three long-running processes** from this one
repo, plus a Railway Redis plugin. Postgres is **external** (Supabase) —
Railway never touches the database schema.

| Service | Start command | Notes |
|---|---|---|
| `web`    | `uv run uvicorn backend.main:app --host 0.0.0.0 --port $PORT` | FastAPI, public |
| `worker` | `uv run celery -A backend.workers.tasks worker --loglevel=info` | Celery, private |
| `bot`    | `uv run python -m backend.telegram.bot` | aiogram polling, private |

The frontend stays on **Vercel** — it is not deployed to Railway.

---

## 1. Install & link the Railway CLI

> Skip this section if you don't have Railway account access yet — these
> steps are for whoever has the account.

```bash
curl -fsSL https://railway.com/install.sh | sh
railway login
cd /home/aswinmanohar/nutrichat
railway init        # creates a new project, or:
railway link         # link to an existing project
```

---

## 2. Add Redis

In the Railway dashboard (or `railway add`), add the **Redis** plugin to the
project. Railway provisions an internal `REDIS_URL` you'll reference from
all three services (see env vars below) — use the **internal** connection
string (`redis://default:<password>@redis.railway.internal:6379`), not the
public proxy, to avoid egress costs/latency.

---

## 3. Create the three services

From the repo root, create three separate services, all pointing at the
same GitHub repo / branch:

```bash
railway add --service web
railway add --service worker
railway add --service bot
```

For each service:

1. Connect it to this repo (Settings -> Source -> GitHub repo).
2. Build: leave as **NIXPACKS** — `nixpacks.toml` + `railway.json` at the
   repo root configure Python 3.13 + `uv sync --frozen`.
3. Set the **Custom Start Command** (Settings -> Deploy):
   - `web`: leave as default — `railway.json` already sets
     `uv run uvicorn backend.main:app --host 0.0.0.0 --port $PORT`.
   - `worker`: `uv run celery -A backend.workers.tasks worker --loglevel=info`
   - `bot`: `uv run python -m backend.telegram.bot`
4. Only `web` needs a public domain (Settings -> Networking -> Generate
   Domain). `worker` and `bot` should remain private (no public networking).
5. Do **not** add a release/deploy-time `alembic upgrade head` step on any
   service — the Supabase schema is managed manually via migrations applied
   through the Supabase MCP/SQL editor, independent of app deploys.

---

## 4. Environment variables (shared across web / worker / bot)

Set these as **shared variables** at the project level so all three services
inherit them (Railway: Project Settings -> Shared Variables), then
reference with `${{shared.VAR_NAME}}` in each service if needed.

```bash
# --- Database (Supabase) -----------------------------------------------
# CRITICAL: use the Supabase SESSION POOLER connection string, NOT the
# direct db.<ref>.supabase.co host and NOT the transaction pooler (port 6543).
#
#   - Direct host (db.<ref>.supabase.co) is IPv6-only — Railway egress may
#     not reach it.
#   - Transaction pooler (port 6543) breaks asyncpg/psycopg prepared
#     statements used by SQLAlchemy + LangGraph's AsyncPostgresSaver.
#   - Session pooler (port 5432, aws-0-<region>.pooler.supabase.com) is
#     IPv4-reachable and supports prepared statements.
#
# Get it from: Supabase Dashboard -> Connect -> Session pooler. Keep the
# `+asyncpg` driver suffix and URL-encode the password (e.g. `@` -> `%40`).
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<url-encoded-password>@aws-0-<region>.pooler.supabase.com:5432/postgres

# --- Redis (Railway plugin, internal URL) -------------------------------
REDIS_URL=redis://default:<password>@redis.railway.internal:6379

# --- LLM providers --------------------------------------------------------
GOOGLE_API_KEY=
ANTHROPIC_API_KEY=
TYPESAFE_API_KEY=        # Jev intent routing (web + bot); optional

# --- USDA FoodData Central ------------------------------------------------
USDA_API_KEY=

# --- Supabase Auth ---------------------------------------------------------
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_JWT_SECRET=
SUPABASE_ANON_KEY=

# --- Observability (Logfire) ------------------------------------------------
LOGFIRE_TOKEN=
LOGFIRE_ENVIRONMENT=production
# Alternative: disable Logfire entirely instead of setting a token
# LOGFIRE_ENABLED=false

# --- Auth bypass — MUST be false in production ------------------------------
DEV_BYPASS_AUTH=false

# --- Telegram bot (polling mode — no public URL needed) ---------------------
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
TELEGRAM_USE_WEBHOOK=false

# --- CORS: allow the Vercel frontend ----------------------------------------
# Comma-separated if you have multiple Vercel URLs (prod + preview).
FRONTEND_ORIGIN=https://<your-frontend>.vercel.app
```

Notes:

- `web` is the only service that strictly needs `FRONTEND_ORIGIN` (CORS),
  `SUPABASE_*`, and a public domain — but setting all vars as shared keeps
  things simple and lets any service import `backend.main` (e.g. for
  one-off scripts) without missing env vars.
- `worker` and `bot` both need `DATABASE_URL`, `REDIS_URL`,
  `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `USDA_API_KEY`, `LOGFIRE_*`. `bot`
  additionally needs `TELEGRAM_*` and `SUPABASE_JWT_SECRET` (for `/link`
  flows via the API, if applicable).

---

## 5. Vercel frontend env vars

In the Vercel project (unchanged deployment target):

```bash
VITE_API_URL=https://<web-service>.up.railway.app
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=
```

Redeploy the frontend after setting these so the build picks them up.

---

## 6. Post-deploy verification

```bash
# 1. Web service is up
curl https://<web-service>.up.railway.app/health
# expect: {"status":"ok"}

# 2. Mint an integration token for a real user (run locally against prod DB,
#    or via a Railway shell: `railway run --service web -- python -m backend.scripts.mint_token ...`)
python -m backend.scripts.mint_token --user-id <uuid> --name "life-os"

# 3. Exercise the integration API with the minted token
curl -H "Authorization: Bearer nck_<token>" \
  https://<web-service>.up.railway.app/v1/integrations/health

curl -H "Authorization: Bearer nck_<token>" \
  "https://<web-service>.up.railway.app/v1/integrations/meals?limit=5"

# 4. Telegram bot — confirm the bot process is polling
#    Open Telegram, message your bot:
#      /start   -> should greet you
#      /link    -> should return a link code to pair with your NutriChat account
```

If `/health` or the integration endpoints fail, check the `web` service
logs for `DATABASE_URL` connection errors first — this is almost always the
session-pooler vs. direct-host issue described above.
