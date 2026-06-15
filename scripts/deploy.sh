#!/usr/bin/env bash
#
# deploy.sh — push the latest code/config to NutriChat's live Railway services.
#
# WHAT THIS DOES:
#   After you edit src/backend/config/tunables.yaml (or any other file),
#   run this script to redeploy the three backend services so your changes
#   go live: web (the API), bot (Telegram), worker (background jobs).
#
# HOW TO USE:
#   1. Open a terminal in the nutrichat project folder.
#   2. Run:  bash scripts/deploy.sh
#   3. Wait ~2-3 minutes, then test your change in the app / Telegram.
#
# REQUIREMENTS:
#   - You must be logged into Railway (railway login) — already done on
#     this machine.
#   - The Railway CLI must be installed at ~/.railway/bin/railway.
#
set -euo pipefail

RAILWAY="$HOME/.railway/bin/railway"
MESSAGE="config/prompt update"

echo "Starting deploy to Railway..."
echo ""

echo "Deploying web..."
"$RAILWAY" up --service web --detach -m "$MESSAGE"

echo "Deploying bot..."
"$RAILWAY" up --service bot --detach -m "$MESSAGE"

echo "Deploying worker..."
"$RAILWAY" up --service worker --detach -m "$MESSAGE"

echo ""
echo "Done — changes go live in ~2-3 minutes."
echo "You can check progress in the Railway dashboard."
