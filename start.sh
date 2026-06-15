#!/usr/bin/env bash
# Railway process dispatcher. One image, three services — each sets PROC.
#   web    → FastAPI (binds $PORT)
#   worker → Celery worker
#   bot    → Telegram bot (polling)
set -euo pipefail

case "${PROC:-web}" in
  web)
    exec uv run uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  worker)
    # Cap concurrency: Celery defaults to host CPU count (48 on Railway),
    # and each prefork child loads the full LLM/LangGraph stack -> OOM.
    exec uv run celery -A backend.workers.tasks worker --loglevel=info \
      --concurrency="${CELERY_CONCURRENCY:-2}" --without-gossip --without-mingle
    ;;
  bot)
    exec uv run python -m backend.telegram.bot
    ;;
  *)
    echo "Unknown PROC='${PROC:-}'. Expected web|worker|bot." >&2
    exit 1
    ;;
esac
