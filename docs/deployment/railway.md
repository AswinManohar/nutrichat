# Railway deployment runbook (backend)

Mealsy's backend (formerly NutriChat; infra identifiers keep the old name) runs as **three long-running services** from this one repo,
plus a Railway **Redis** plugin. Postgres is **external** (Supabase) — Railway
never touches the database schema. The **frontend is on Netlify** (see
[`netlify.md`](./netlify.md)), not Railway.

> **This is the live setup.** The project already exists and is deployed — most
> teammates only need the **[Routine deploy](#routine-deploy-the-95-case)**
> section. The [first-time setup](#first-time-setup-already-done---reference-only)
> is reference for rebuilding from scratch.

| Railway resource | What it is |
|---|---|
| Workspace | `aswinmanohar's Projects` (Free plan) |
| Project | `nutrichat` (`e0045c62-b2fc-4561-b27d-9b1b8ac5b3c7`) |
| Environment | `production` |
| Service `web` | FastAPI, **public** — `web-production-e3eea.up.railway.app` |
| Service `worker` | Celery worker, private |
| Service `bot` | aiogram Telegram bot (polling), private |
| Plugin `Redis` | Railway Redis + `redis-volume`, internal only |

All three app services build the **same repo** with NIXPACKS and run
`bash start.sh`; `start.sh` dispatches on the per-service **`PROC`** variable
(`web` / `worker` / `bot`). Config lives in `railway.json` + `nixpacks.toml` at
the repo root.

> **Free-plan limit:** the 4 resources above max out the Free plan. You cannot
> provision a parallel environment (e.g. `test`) or a 5th service without
> upgrading. Deploys happen via the CLI (`railway up`) from a local checkout —
> the services are **not** GitHub-connected, so `git push` does **not** deploy.

---

## CLI prerequisites (once per machine)

The Railway CLI lives at `~/.railway/bin/railway` (not always on `PATH`). Install
if missing, then authenticate:

```bash
curl -fsSL https://railway.com/install.sh | sh
~/.railway/bin/railway login           # opens a browser; new accounts sign up here too
~/.railway/bin/railway whoami          # confirm: aswinbio@gmail.com
```

Link this repo's directory to the project + environment (once per clone):

```bash
cd /path/to/nutrichat
~/.railway/bin/railway link \
  --project e0045c62-b2fc-4561-b27d-9b1b8ac5b3c7 \
  --environment production --service web
~/.railway/bin/railway status          # confirm Project=nutrichat, Environment=production
```

---

## Routine deploy (the 95% case)

Deploys upload your **local working tree** (respecting `.gitignore`, so `.env`
and `.mcp.json` are never uploaded) and build it on Railway. Always deploy from
a clean checkout of the branch you intend to ship — production runs the
`production` branch.

```bash
cd /path/to/nutrichat
git switch production && git pull         # ship exactly what's on the production branch
git status --short                        # MUST be clean — railway up sends the working tree

RW=~/.railway/bin/railway
export RAILWAY_CALLER="manual-deploy"      # shows up in deploy metadata/telemetry

# Deploy each app service (same code, different PROC). --detach returns at QUEUED.
$RW up --service web    --detach -m "describe what changed"
$RW up --service worker --detach -m "describe what changed"
$RW up --service bot    --detach -m "describe what changed"
```

**Only redeploy the services a change touches.** A frontend-only or API-only
change usually needs just `web`; redeploy `worker`/`bot` when shared backend code
or dependencies change, to keep all three on one commit.

Watch a build / confirm it succeeded (don't trust the QUEUED return):

```bash
$RW deployment list --service web --environment production --json | head
#   look for "status": "SUCCESS"   (BUILDING -> DEPLOYING -> SUCCESS)
$RW logs --service web --environment production    # live logs if a build fails
```

> **Rollback:** `railway deployment list --service <svc>` shows prior deployment
> IDs; redeploy a known-good one from the dashboard (Deployments → ⋯ → Redeploy),
> or `railway redeploy --service <svc>` to re-run the latest. `railway down
> --service <svc>` removes the active deployment — **don't** run it on `web`
> unless you intend to take production offline.

### Schema migrations are NOT part of deploy
There is no release/`alembic upgrade` step. The Supabase schema is applied
**manually** (Supabase MCP / SQL editor) before/independent of an app deploy.
Deploying never migrates the database.

---

## Environment variables

Set per service in the Railway dashboard (Service → Variables) or via
`railway variables --service <svc> --set KEY=value`. **Never** paste real secrets
into this file, commits, or chat. `web` needs the full set; `worker`/`bot` need
everything except the CORS/Supabase-auth bits (noted below).

```bash
# --- Database (Supabase) — CRITICAL: use the SESSION POOLER string ----------
#   * NOT the direct db.<ref>.supabase.co host (IPv6-only; Railway can't reach).
#   * NOT the transaction pooler (port 6543; breaks asyncpg/psycopg prepared
#     statements used by SQLAlchemy + LangGraph AsyncPostgresSaver).
#   * Session pooler (port 5432, aws-0-<region>.pooler.supabase.com) is
#     IPv4-reachable and supports prepared statements.
#   Supabase Dashboard -> Connect -> Session pooler. Keep `+asyncpg` and
#   URL-encode the password (e.g. `!` -> `%21`, `@` -> `%40`).
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<url-encoded-pw>@aws-0-<region>.pooler.supabase.com:5432/postgres

# --- Redis (Railway plugin, INTERNAL url — avoids egress cost/latency) -------
REDIS_URL=redis://default:<password>@redis.railway.internal:6379

GOOGLE_API_KEY=            # web, worker, bot
ANTHROPIC_API_KEY=         # fallback / eval
TYPESAFE_API_KEY=          # web, bot — Jev intent routing; optional (unset = Gemini routes everything)
USDA_API_KEY=

# --- Supabase Auth (web needs these; bot needs JWT secret for /link) ---------
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_JWT_SECRET=
SUPABASE_ANON_KEY=

# --- Observability -----------------------------------------------------------
LOGFIRE_TOKEN=
LOGFIRE_ENVIRONMENT=production

# --- CORS: allow the Netlify frontend (web only) -----------------------------
# Comma-separated for multiple origins (prod + Netlify deploy previews).
FRONTEND_ORIGIN=https://<your-site>.netlify.app

# --- Telegram bot (polling mode — no public URL needed) ----------------------
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
TELEGRAM_USE_WEBHOOK=false

# --- PROC: set ONCE per service, do not change -------------------------------
#   web service -> PROC=web   worker service -> PROC=worker   bot service -> PROC=bot
```

> **`DEV_BYPASS_AUTH` is gone.** As of the production cutover the backend no
> longer reads it — auth is always enforced via Supabase JWT. You can delete the
> variable from every service; leaving it set has no effect.

---

## First-time setup (already done — reference only)

To rebuild the project from scratch:

1. `railway login` then `railway init` (creates the `nutrichat` project).
2. `railway add --database redis` — provisions the Redis plugin.
3. Create three services and set each one's `PROC`:
   ```bash
   railway add --service web    --variables "PROC=web"
   railway add --service worker --variables "PROC=worker"
   railway add --service bot    --variables "PROC=bot"
   ```
   Build stays **NIXPACKS** (configured by `nixpacks.toml` + `railway.json`);
   start command is `bash start.sh` for all three (from `railway.json`).
4. Set the env vars above on each service (project-level shared variables also
   work — reference with `${{shared.VAR}}`).
5. `web` only: Settings → Networking → **Generate Domain** (public). Keep
   `worker` and `bot` private.
6. Deploy each service with `railway up --service <svc>` (see Routine deploy).

> **Upgrading for a real `test` environment:** the Free plan can't host a second
> environment. On a paid plan, duplicate `production` → `test`, then either
> deploy to it with `railway up` (after `railway link --environment test`) or
> connect the services to GitHub (`railway add --repo AswinManohar/nutrichat
> --branch production`) so pushes auto-deploy. Validate there before production.

---

## Post-deploy verification

```bash
# 1. web is up
curl https://web-production-e3eea.up.railway.app/health      # -> {"status":"ok"}

# 2. auth is enforced (no dev bypass) — protected route without a token
curl -o /dev/null -w "%{http_code}\n" \
  https://web-production-e3eea.up.railway.app/goals           # -> 401

# 3. worker / bot are RUNNING
~/.railway/bin/railway deployment list --service worker --environment production --json | head
~/.railway/bin/railway deployment list --service bot    --environment production --json | head

# 4. Telegram bot is polling — message it: /start (greets), /link (returns a code)
```

If `/health` fails, check `web` logs for `DATABASE_URL` errors first — it's
almost always the session-pooler vs. direct-host issue described above.
```bash
~/.railway/bin/railway logs --service web --environment production
```
