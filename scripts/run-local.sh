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
#   --worker   also start the Celery worker
#   --bot      also start the Telegram bot in polling mode
#              (WARNING: only one poller per bot token is allowed —
#               do NOT use this while the Railway "bot" service is running,
#               or both will get TelegramConflictError)
#
# Usage:
#   bash scripts/run-local.sh [--worker] [--bot]
#
# Press Ctrl+C to stop everything.
set -euo pipefail

cd "$(dirname "$0")/.."

WITH_WORKER=false
WITH_BOT=false
for arg in "$@"; do
  case "$arg" in
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

echo "Starting Redis (docker compose)..."
if ! docker compose up -d redis; then
  echo "  WARNING: couldn't start Redis via docker (permission denied?)."
  echo "  Fix once with: sudo usermod -aG docker \$USER  (then log out/in)"
  echo "  Continuing without Redis -- caching/session features will fail."
fi

echo "Starting backend API on http://localhost:8000 ..."
uv run --env-file .env uvicorn backend.main:app --reload --port 8000 --app-dir src \
  > logs/web.log 2>&1 &
PIDS+=($!)

echo "Starting frontend on http://localhost:5173 ..."
(cd frontend && npm run dev > ../logs/frontend.log 2>&1) &
PIDS+=($!)

if [ "$WITH_WORKER" = true ]; then
  echo "Starting Celery worker..."
  uv run --env-file .env celery -A backend.workers.tasks worker --loglevel=info \
    --concurrency=2 --without-gossip --without-mingle \
    > logs/worker.log 2>&1 &
  PIDS+=($!)
fi

if [ "$WITH_BOT" = true ]; then
  echo "Starting Telegram bot (polling)..."
  echo "  WARNING: stop the Railway 'bot' service first, or you'll get TelegramConflictError."
  uv run --env-file .env python -m backend.telegram.bot > logs/bot.log 2>&1 &
  PIDS+=($!)
fi

echo ""
echo "All set. Logs: logs/*.log (tail -f logs/web.log etc.)"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop everything."
echo ""

wait
