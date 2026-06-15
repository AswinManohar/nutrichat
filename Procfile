# Reference only — Railway does not read Procfile when using NIXPACKS with
# railway.json. Each process below maps to its own Railway service with a
# Custom Start Command set in the dashboard (see docs/deployment/railway.md).
#
# Postgres is external (Supabase) — do NOT add a release/alembic step here;
# schema migrations are applied manually via Supabase MCP/SQL.

web: uv run uvicorn backend.main:app --host 0.0.0.0 --port $PORT
worker: uv run celery -A backend.workers.tasks worker --loglevel=info
bot: uv run python -m backend.telegram.bot
