# CLAUDE.md — Mealsy

Mealsy is a production nutrition app (renamed from "NutriChat"; the git repo
directory is still `nutrichat/` and some infra identifiers keep the old name — see
docs/deployment/deploy-guide.md). It tracks calories, macronutrients and
micronutrients, adapts to each user, and provides personalized coaching based on
their eating habits. Users describe meals in natural language; the agent extracts
food entities, resolves them against USDA FoodData Central, and tracks them against
the user's goals. It is not a demo or learning project: treat changes as changes to
a live app with real users.

**Scope.** Active development covers the Android app (`android/`) and the
backend services it uses (`src/backend/`). The web frontend (`frontend/`) is
not being developed: do not add features or refactor there, and do not propose
web work. It is still deployed and its tests and build still run in the
production checks, so only touch it when a backend change would otherwise break
them.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13 · FastAPI · async · SQLAlchemy 2 (asyncpg) · uv |
| Agent | LangGraph (logging, Postgres checkpointer) · Pydantic AI (coaching) |
| Observability | Logfire (OpenTelemetry) |
| LLM — extraction | Gemini 2.5 Flash (thinking disabled — see tunables `extraction_thinking_budget`) |
| LLM — coaching | Gemini 2.5 Flash |
| Typed judgments | TypeSafe Jev (System One): log/coaching intent routing; Gemini classifier as safety net |
| Database | PostgreSQL 16 + pgvector |
| Cache | Redis |
| Task queue | Celery + Redis |
| Embeddings | Gemini gemini-embedding-001 (768-dim via output_dimensionality) |
| Auth | Supabase Auth (ES256 JWTs via JWKS; no dev bypass) |
| Web frontend (not in active development) | React 19 · TypeScript · Vite · Tailwind CSS 4 · TanStack Query · Zustand |
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
│   │   ├── system_one.py       # TypeSafe Jev routing judgment (judge_message)
│   │   ├── coaching.py         # Pydantic AI coaching agent
│   │   ├── coaching_store.py   # persist each coaching turn for feedback/eval
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
│   │                           # coaching_feedback, nutrient_checkup, mindful, quota,
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
├── frontend/src/               # web app, not in active development
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
GOOGLE_API_KEY=          # Gemini 2.5 Flash + embeddings
ANTHROPIC_API_KEY=       # reserved; not used by current code
TYPESAFE_API_KEY=        # Jev intent routing; unset = Gemini routes everything
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

# Web frontend (not in active development; only to run its checks)
cd frontend && npm run dev
cd frontend && npm test          # Vitest

# Eval
python eval/run_eval.py --dataset eval/test_set_200.jsonl --mock  # offline
python eval/run_eval.py --dataset eval/test_set_200.jsonl          # live
python eval/gate.py --only intent_routing --runs 5 \
    --baseline eval/baseline_intent_legacy.json                   # routing gate
python eval/probe_jev_latency.py --n 50 --concurrency 1,5,10      # Jev latency
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
- **Gemini key and spend cap.** `GOOGLE_API_KEY` in `.env` belongs to Google
  project `gen-lang-client-0523573857`. When its monthly spend cap is hit,
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

## Git

- **Branches.** Work on a feature branch (`feat/<name>` or the spec's
  `NNN-name`). `master` is the main branch and the PR target. `production` is
  what gets deployed.
- **Never commit, cherry-pick or push to `production` directly.** Ship only
  through `scripts/push-to-production.sh` (or `/ship`), and only when asked to
  in that turn. A plain "commit" or "push" means the feature branch.
- **Commit messages** follow Conventional Commits: `type(scope): summary`, with
  types `feat`, `fix`, `test`, `docs`, `refactor`, `chore`. Write the summary in
  the imperative and keep it under about 72 characters. Add the spec task ID
  when there is one, for example `(T035)`.
- **One logical change per commit.** During implementation, commit after each
  completed task and push the feature branch.
- **Authorship.** Commit under the repo's configured git identity. Do not add
  AI co-author trailers.
- **Stage only what you changed.** The working tree usually holds unrelated
  uncommitted edits and untracked files. Never use `git add -A` or `git add .`;
  if a file mixes your edits with someone else's, stage only your hunks.
- **Never commit secrets** (`.env`, API keys, `.aws/`, service-account JSON).
  Gitleaks runs in the production checks.
- **Ask before anything destructive or history-rewriting:** force-push,
  `reset --hard`, `clean`, rebasing pushed commits, deleting branches. Never
  bypass hooks with `--no-verify`.
- **Always resolve conflicts before moving to a feature branch.** Finish or
  abort any merge, rebase or cherry-pick first, and never switch branches with
  unresolved conflict markers in the tree. Resolve by reading both sides; do
  not blanket-accept one of them.

---

## Code quality

- **Match the gate.** A change is done when it would pass
  `scripts/prod-checks.sh`: no new Ruff findings in changed Python files,
  backend pytest, frontend Vitest, `tsc` + Vite build, gitleaks, bandit (high
  severity), and no dependency vulnerabilities beyond
  `security/audit-baseline.json`.
- **Test what you change.** New behavior gets a test; a bug fix gets a test
  that fails without the fix. Run the tests for the code you touched before
  committing, and report failures as they are.
- **Changes to prompts, routing or the USDA ranker need an eval run**
  (`eval/gate.py`) against the current baseline, not only unit tests.
- **NEVER add a dependency without asking first.** This covers Python
  (`pyproject.toml`), npm (`package.json`) and Gradle
  (`gradle/libs.versions.toml`), including dev dependencies and version
  upgrades. Say what it is for and why existing code or libraries don't cover
  it, then wait for approval.
- **Keep diffs small and on topic.** No drive-by refactors or reformatting of
  files you are not otherwise changing. Lint and format only the files you
  touch.
- **Protect chat-turn latency.** Do not add sequential I/O or an extra LLM call
  to a chat turn without stating its latency and cost. Run independent I/O in
  parallel.
- **No dead code.** Remove unused code, commented-out blocks and stray debug
  logging instead of leaving them behind. Tunable values belong in
  `config/tunables.yaml` and prompts in `config/prompts/`, not inline.
- **Fail visibly.** Log errors with context and surface them to the user. Do
  not swallow exceptions or return a silent default.
- **Comments explain why, not what.** Update docs (this file,
  `docs/architecture.md`) when layout, commands or behavior change.

---

## Database

Three rules, all IMPORTANT:

1. **One source of truth.** Never store the same fact twice, whether in a
   column, JSONB, a config list or a client-side constant. Derive totals on
   read instead of persisting them next to their parts. If a copy is truly
   needed (an immutable historical snapshot, a performance cache), say so and
   justify it. Flag duplication when proposing a schema.
2. **Schema changes go through Alembic migrations only.** Never alter the
   schema by hand. Migrations are append-only: do not edit one that has been
   applied to production; add a new one. Check for revision-number clashes with
   other open branches first. New user-data tables need RLS policies, foreign
   keys and indexes for the columns they are queried by.
3. **Protect production data.** The `DATABASE_URL` in `.env` is the live
   Supabase database. Never point tests, or a branch with unshipped migrations,
   at it. Never run destructive SQL (`DELETE`, `UPDATE`, `DROP`, `TRUNCATE`)
   against production without explicit approval in that turn.

---

## Python coding standards

Follows the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
and [PEP 8](https://peps.python.org/pep-0008/).

- **Naming.** `snake_case` for modules, functions and variables; `PascalCase`
  for classes and type aliases; `UPPER_SNAKE_CASE` for module-level constants;
  a leading underscore for private helpers.
- **Types.** Annotate every function, including a `-> None` return. Start every
  file with `from __future__ import annotations`. Use `T | None` or
  `Optional[T]` for optional values.
- **Docstrings.** Google style, with `Args`, `Returns` and `Raises` on public
  functions. A one-line docstring is enough for a simple private helper.
- **Imports.** Order them stdlib, third-party, local, with a blank line between
  groups. No wildcard imports. No imports inside function bodies except to
  break a circular import, with a comment saying so.
- **Errors.** Catch specific exceptions; never use a bare `except`. Log with
  context and then handle or re-raise. Use custom exception classes for domain
  errors.
- **Async.** All I/O is async. Never call blocking functions (`time.sleep`,
  `requests`) from async code. Use `asyncio.gather` for independent calls
  instead of awaiting them in a loop.
- **Data at boundaries.** Use Pydantic models for anything that crosses a
  boundary (tool input/output, API request/response, database row), not raw
  dicts. Set `extra = "forbid"` so unknown fields are rejected.
- **Formatting.** Max line length is 88. Use Ruff for linting and formatting
  (`uv run ruff check --fix <file>`, `uv run ruff format <file>`). Do not run
  Black: it is not installed in the venv, and `uvx black` disagrees with Ruff
  on existing files.

---

## Android development

Applies to `android/` (Kotlin, Jetpack Compose, Hilt, Retrofit, Room). The
design-system rules are in `android/CLAUDE.md`.

- Use AndroidX/Jetpack APIs and the libraries already in
  `gradle/libs.versions.toml` when they cover the need. Adding a dependency
  needs approval first (see Code quality).
- Screens go in `app/.../ui/<feature>/`. Shared composables go in `:core:ui`
  (or `ui/common/` when they are app-specific).
- Navigation routes MUST be defined in `ui/AppNav.kt`.
- Style with the `MealsyColors`, `MealsyType` and `MealsyShapes` tokens from
  `:core:ui`. No hard-coded colors, text styles or radii in composables.
- All backend requests go through `MealsyApi` in `:core:data`. No direct
  OkHttp or `HttpURLConnection` calls from screens or view models.
- IMPORTANT: Test on a device (the Pixel 9, or the emulator as fallback) in
  both light and dark theme before calling UI work done.
- NEVER store sensitive data (tokens, passwords) in plain SharedPreferences,
  DataStore or Room, and never log it. Session tokens stay in supabase-kt's
  session storage; anything else sensitive uses Keystore-backed encryption.

---

## Decisions still to make

Things that should be decided as the project develops, not upfront:

- Error monitoring: Sentry vs structured logging to Railway
- Streaming: whether to stream LLM responses token-by-token or return complete
- Voice input: Whisper API or browser Web Speech API (Phase 2)
- Testing framework: pytest fixtures strategy as the agent grows

Add a decision record here when each is settled.
