#!/usr/bin/env bash
#
# deploy-railway.sh — deploy the NutriChat backend to Railway.
#
# Railway deploys via `railway up`, which uploads the current working tree
# (respecting .gitignore, so .env / .mcp.json are never sent) and builds it
# with NIXPACKS. There is NO GitHub auto-deploy and NO alembic step — the
# Supabase schema is managed separately. See docs/deployment/railway.md.
#
# Usage:
#   scripts/deploy-railway.sh [options] [service ...]
#
#   service ...     One or more of: web worker bot   (default: all three)
#   -m "msg"        Deploy message (default: branch + short SHA)
#   -b branch       Git branch the working tree must be on (default: production)
#   --allow-dirty   Skip the clean-working-tree check (deploys uncommitted edits)
#   --no-wait       Trigger deploys and exit without polling for success
#   -h, --help      Show this help
#
# Examples:
#   scripts/deploy-railway.sh                 # deploy web + worker + bot
#   scripts/deploy-railway.sh web             # deploy only web
#   scripts/deploy-railway.sh -m "hotfix" web worker
#
set -euo pipefail

# --- Project constants (from `railway status`) -------------------------------
PROJECT_ID="e0045c62-b2fc-4561-b27d-9b1b8ac5b3c7"
ENVIRONMENT="production"
WEB_HEALTH_URL="https://web-production-e3eea.up.railway.app/health"
ALL_SERVICES=(web worker bot)

# Show up in Railway deploy metadata/telemetry.
export RAILWAY_CALLER="${RAILWAY_CALLER:-deploy-railway.sh}"
export RAILWAY_AGENT_SESSION="${RAILWAY_AGENT_SESSION:-deploy-$(date +%s)-$$}"

# --- Defaults / arg parsing --------------------------------------------------
EXPECTED_BRANCH="production"
DEPLOY_MSG=""
ALLOW_DIRTY=0
WAIT=1
SERVICES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m) DEPLOY_MSG="${2:?-m needs a message}"; shift 2 ;;
    -b) EXPECTED_BRANCH="${2:?-b needs a branch}"; shift 2 ;;
    --allow-dirty) ALLOW_DIRTY=1; shift ;;
    --no-wait) WAIT=0; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    web|worker|bot) SERVICES+=("$1"); shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ ${#SERVICES[@]} -eq 0 ]] && SERVICES=("${ALL_SERVICES[@]}")

# --- Locate repo root and the Railway CLI ------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if command -v railway >/dev/null 2>&1; then
  RW="$(command -v railway)"
elif [[ -x "$HOME/.railway/bin/railway" ]]; then
  RW="$HOME/.railway/bin/railway"
else
  echo "ERROR: Railway CLI not found. Install: curl -fsSL https://railway.com/install.sh | sh" >&2
  exit 1
fi

# --- Preflight checks --------------------------------------------------------
echo "==> Railway CLI: $RW ($($RW --version))"

if ! $RW whoami >/dev/null 2>&1; then
  echo "ERROR: not logged in. Run: $RW login" >&2
  exit 1
fi
echo "==> Authenticated as: $($RW whoami 2>/dev/null | grep -i email | head -1 | tr -d '\r')"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "$EXPECTED_BRANCH" ]]; then
  echo "ERROR: on branch '$BRANCH', expected '$EXPECTED_BRANCH'." >&2
  echo "       Switch with: git switch $EXPECTED_BRANCH   (or override with -b $BRANCH)" >&2
  exit 1
fi

if [[ $ALLOW_DIRTY -eq 0 && -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree is dirty — railway up uploads the working tree, not the commit." >&2
  echo "       Commit/stash your changes, or pass --allow-dirty to deploy them anyway." >&2
  git status --short >&2
  exit 1
fi

SHA="$(git rev-parse --short HEAD)"
[[ -z "$DEPLOY_MSG" ]] && DEPLOY_MSG="$BRANCH @ $SHA"

echo "==> Linking to project=$PROJECT_ID environment=$ENVIRONMENT"
$RW link --project "$PROJECT_ID" --environment "$ENVIRONMENT" --service "${SERVICES[0]}" >/dev/null

echo "==> Deploying [${SERVICES[*]}] from $BRANCH ($SHA): \"$DEPLOY_MSG\""
echo

# --- Trigger deploys ---------------------------------------------------------
for svc in "${SERVICES[@]}"; do
  echo "--- railway up --service $svc ---"
  $RW up --service "$svc" --environment "$ENVIRONMENT" --detach -m "$DEPLOY_MSG"
done

if [[ $WAIT -eq 0 ]]; then
  echo
  echo "==> Triggered (--no-wait). Check status: $RW deployment list --service web --environment $ENVIRONMENT"
  exit 0
fi

# --- Poll each service's latest deployment until terminal --------------------
deploy_status() {
  $RW deployment list --service "$1" --environment "$ENVIRONMENT" --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['status'] if d else 'UNKNOWN')" 2>/dev/null \
    || echo "UNKNOWN"
}

echo
echo "==> Waiting for deployments (timeout ~10 min)..."
FAILED=0
for svc in "${SERVICES[@]}"; do
  for _ in $(seq 1 40); do
    st="$(deploy_status "$svc")"
    case "$st" in
      SUCCESS) echo "    $svc: SUCCESS"; break ;;
      FAILED|CRASHED|REMOVED) echo "    $svc: $st  <-- check: $RW logs --service $svc --environment $ENVIRONMENT" >&2; FAILED=1; break ;;
      *) printf "    %s: %-12s\r" "$svc" "$st"; sleep 15 ;;
    esac
  done
done

# --- Post-deploy health check ------------------------------------------------
if printf '%s\n' "${SERVICES[@]}" | grep -qx web; then
  echo "==> web health: $(curl -s -m 10 "$WEB_HEALTH_URL" || echo '(unreachable)')"
fi

if [[ $FAILED -ne 0 ]]; then
  echo "==> One or more services failed to deploy." >&2
  exit 1
fi
echo "==> Done."
