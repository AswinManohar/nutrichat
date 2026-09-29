#!/usr/bin/env bash
#
# run-local.sh — launch NutriChat locally for testing.
#
# Starts (by default):
#   - Redis (docker compose)
#   - Backend API   -> http://localhost:8000
#   - Frontend      -> http://localhost:5173
#
# Optional extras:
#   --local-db use the docker Postgres on :5411 instead of the DATABASE_URL in
#              .env (also starts the db container and waits for it). The database
#              name defaults to nutrichat_sdd; override with LOCAL_DB=<name>.
#              Why nutrichat_sdd: the local `nutrichat` DB is stamped at the
#              android branch's Alembic head (013), which this branch cannot
#              resolve. Switch to LOCAL_DB=nutrichat once the branches merge.
#   --worker   also start the Celery worker
#   --bot      also start the Telegram bot in polling mode
#              (WARNING: only one poller per bot token is allowed —
#               do NOT use this while the Railway "bot" service is running,
#               or both will get TelegramConflictError)
#
# Usage:
#   bash scripts/run-local.sh [--local-db] [--worker] [--bot]
#
# Press Ctrl+C to stop everything.
set -euo pipefail

cd "$(dirname "$0")/.."

WITH_WORKER=false
WITH_BOT=false
LOCAL_DB_MODE=false
LOCAL_DB="${LOCAL_DB:-nutrichat_sdd}"
for arg in "$@"; do
  case "$arg" in
    --local-db) LOCAL_DB_MODE=true ;;
    --worker) WITH_WORKER=true ;;
    --bot) WITH_BOT=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

mkdir -p logs
PIDS=()

cleanup() {
  echo ""
  echo "Stopping..."
  for pid in "${PIDS[@]}"; do
    # Kill the whole process group so child processes (e.g. vite's esbuild,
    # uvicorn's reload worker) don't linger after the script exits.
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

# Kill anything left over from a previous run that wasn't shut down cleanly
# (e.g. the terminal was closed instead of pressing Ctrl+C).
echo "Clearing stale processes on ports 8000/5173..."
for port in 8000 5173; do
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  killing leftover process(es) on port $port: $pids"
    kill -9 $pids 2>/dev/null || true
  fi
done

# Wait until a TCP port answers, or give up.
wait_for_port() {
  local name="$1" host="$2" port="$3" tries="${4:-30}"
  for _ in $(seq 1 "$tries"); do
    if (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; then
      exec 3>&- 3<&-
      return 0
    fi
    sleep 1
  done
  echo "  ERROR: $name did not accept connections on $host:$port" >&2
  return 1
}

# Load .env into the environment. In --local-db mode the DB and Redis URLs
# are overridden below, so we do not use `uv run --env-file`, which would
# reapply .env on top of the overrides.
set -a
# shellcheck disable=SC1091
. ./.env
set +a

# Start a compose service, or restart its container if one with that name
# already exists (a container created by another compose project or by hand
# makes `docker compose up` fail with a name conflict).
start_service() {
  local service="$1" container="$2"
  if docker ps -a --format '{{.Names}}' | grep -qx "$container"; then
    docker start "$container" >/dev/null
  else
    docker compose up -d "$service"
  fi
}

if [ "$LOCAL_DB_MODE" = true ]; then
  echo "Starting Postgres + Redis (docker)..."
  if ! start_service db nutrichat-pg || ! start_service redis nutrichat-redis; then
    echo "  ERROR: couldn't start docker services (permission denied?)." >&2
    echo "  Fix once with: sudo usermod -aG docker \$USER  (then log out/in)" >&2
    exit 1
  fi
  wait_for_port "Postgres" 127.0.0.1 5411
  wait_for_port "Redis" 127.0.0.1 6379
  export DATABASE_URL="postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/${LOCAL_DB}"
  export REDIS_URL="redis://localhost:6379"
  echo "  DATABASE_URL -> local db '${LOCAL_DB}' on :5411"
else
  echo "Starting Redis (docker)..."
  if ! start_service redis nutrichat-redis; then
    echo "  WARNING: couldn't start Redis via docker (permission denied?)."
    echo "  Fix once with: sudo usermod -aG docker \$USER  (then log out/in)"
    echo "  Continuing without Redis -- caching/session features will fail."
  fi
fi

echo "Starting backend API on http://localhost:8000 ..."
uv run uvicorn backend.main:app --reload --port 8000 --app-dir src \
  > logs/web.log 2>&1 &
PIDS+=($!)

echo "Starting frontend on http://localhost:5173 ..."
(cd frontend && npm run dev > ../logs/frontend.log 2>&1) &
PIDS+=($!)

if [ "$WITH_WORKER" = true ]; then
  echo "Starting Celery worker..."
  uv run celery -A backend.workers.tasks worker --loglevel=info \
    --concurrency=2 --without-gossip --without-mingle \
    > logs/worker.log 2>&1 &
  PIDS+=($!)
fi

if [ "$WITH_BOT" = true ]; then
  echo "Starting Telegram bot (polling)..."
  echo "  WARNING: stop the Railway 'bot' service first, or you'll get TelegramConflictError."
  uv run python -m backend.telegram.bot > logs/bot.log 2>&1 &
  PIDS+=($!)
fi

echo "Waiting for the backend health check..."
if ! wait_for_port "backend" 127.0.0.1 8000 60; then
  echo "  Backend failed to start. Last lines of logs/web.log:" >&2
  tail -20 logs/web.log >&2
  exit 1
fi

echo ""
echo "All set. Logs: logs/*.log (tail -f logs/web.log etc.)"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop everything."
echo ""

wait
