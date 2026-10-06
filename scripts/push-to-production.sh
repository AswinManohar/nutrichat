#!/usr/bin/env bash
#
# push-to-production.sh — gate, promote and deploy a commit to production.
#
#   1. checks   scripts/prod-checks.sh (code, migrations, security) on the commit
#   2. confirm  shows what will ship and asks you to type the short SHA
#   3. promote  fast-forwards origin/production to the commit (the pre-push
#               hook re-verifies the checks passed)
#   4. deploy   Railway web/worker/bot + Netlify frontend, from a throwaway
#               worktree of `production` (your working tree is never touched)
#   5. verify   Railway health + Netlify title
#
# Usage:
#   scripts/push-to-production.sh [options] [<commit-or-branch>]   # default: HEAD
#
#   --dry-run        Run the checks and show what would ship; push/deploy nothing
#   --yes            Skip the typed confirmation (for a confirmed /ship run)
#   --skip-checks    Reuse a pass recorded in the last 24 h for this exact commit
#   --backend-only   Deploy Railway only     --frontend-only   Deploy Netlify only
#
# Migrations are NOT applied by this script; the checks block until the
# production database is already at the commit's Alembic head(s).
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
NETLIFY_SITE_ID="e2d088b7-d95d-47b9-83ae-b38eb8e7b7ee"
NETLIFY_URL="https://nutrichat-frontend.netlify.app"
MARKER_DIR="$(cd "$(git rev-parse --git-common-dir)" && pwd)/prod-checks"

DRY_RUN=0; YES=0; SKIP_CHECKS=0; BACKEND=1; FRONTEND=1; TARGET="HEAD"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --yes) YES=1 ;;
    --skip-checks) SKIP_CHECKS=1 ;;
    --backend-only) FRONTEND=0 ;;
    --frontend-only) BACKEND=0 ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    -*) echo "Unknown option: $1" >&2; exit 2 ;;
    *) TARGET="$1" ;;
  esac
  shift
done

git fetch -q origin production
SHA="$(git rev-parse --verify "$TARGET^{commit}")"
SHORT="${SHA:0:8}"
BASE="$(git rev-parse origin/production)"

if [[ "$SHA" == "$BASE" ]]; then
  echo "==> production is already at $SHORT."
  [[ $DRY_RUN -eq 1 ]] && exit 0
elif ! git merge-base --is-ancestor "$BASE" "$SHA"; then
  echo "ERROR: $SHORT does not contain origin/production (${BASE:0:8})." >&2
  echo "       Merge production into your branch first; promotion is fast-forward only." >&2
  exit 1
fi

# --- 1. checks ----------------------------------------------------------------
marker_fresh() {
  [[ -f "$MARKER_DIR/$SHA" ]] && [[ -n "$(find "$MARKER_DIR/$SHA" -mmin -1440)" ]]
}
if [[ $SKIP_CHECKS -eq 1 ]] && marker_fresh; then
  echo "==> Reusing checks passed at $(head -1 "$MARKER_DIR/$SHA") for $SHORT"
else
  "$REPO_ROOT/scripts/prod-checks.sh" "$SHA"
fi

# --- 2. confirm ---------------------------------------------------------------
echo
echo "==> Ready to ship $SHORT to production"
echo "    production: ${BASE:0:8} -> $SHORT ($(git rev-list --count "$BASE..$SHA") commits)"
git --no-pager log --oneline --no-decorate -15 "$BASE..$SHA" | sed 's/^/      /'
echo "    changed areas:"
git diff --dirstat=files,5 "$BASE" "$SHA" | sed 's/^/      /'
echo "    deploy: $([[ $BACKEND -eq 1 ]] && echo 'Railway (web worker bot) ')$([[ $FRONTEND -eq 1 ]] && echo 'Netlify')"
if [[ $DRY_RUN -eq 1 ]]; then
  echo "==> Dry run: nothing pushed or deployed."
  exit 0
fi
if [[ $YES -eq 0 ]]; then
  read -r -p "Type $SHORT to promote and deploy (anything else aborts): " answer
  [[ "$answer" == "$SHORT" ]] || { echo "Aborted."; exit 1; }
fi

# --- 3. promote ---------------------------------------------------------------
if [[ "$SHA" != "$BASE" ]]; then
  echo "==> Pushing $SHORT to origin/production"
  git push origin "$SHA:refs/heads/production"
fi
git update-ref refs/heads/production "$SHA"

# --- 4. deploy ----------------------------------------------------------------
WORK="$(mktemp -d -t proddeploy-XXXXXX)"
cleanup() { git worktree remove --force "$WORK/tree" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT
if ! git worktree add -q "$WORK/tree" production 2>/dev/null; then
  echo "ERROR: could not check out 'production' in a worktree (checked out elsewhere?)." >&2
  git worktree list >&2
  exit 1
fi

DEPLOY_FAILED=0
if [[ $BACKEND -eq 1 ]]; then
  echo "==> Deploying backend to Railway"
  (cd "$WORK/tree" && scripts/deploy-railway.sh -m "production @ $SHORT") || DEPLOY_FAILED=1
fi
if [[ $FRONTEND -eq 1 ]]; then
  echo "==> Deploying frontend to Netlify"
  # Fresh worktree: no frontend/.env.local, so Netlify's VITE_* values are used.
  (cd "$WORK/tree/frontend" && npm ci --silent --no-audit --no-fund \
    && netlify deploy --build --prod --site "$NETLIFY_SITE_ID" \
         --message "production @ $SHORT") || DEPLOY_FAILED=1
fi

# --- 5. verify ----------------------------------------------------------------
if [[ $FRONTEND -eq 1 ]]; then
  title="$(curl -s -m 15 "$NETLIFY_URL" | grep -oiE '<title>[^<]*</title>' || true)"
  echo "==> Netlify: ${title:-(no title — check the site)}"
  [[ -n "$title" ]] || DEPLOY_FAILED=1
fi
if [[ $DEPLOY_FAILED -ne 0 ]]; then
  echo "==> DEPLOY INCOMPLETE: origin/production is at $SHORT but a deploy step failed." >&2
  echo "    Rollback: docs/deployment/deploy-guide.md#rollback" >&2
  exit 1
fi
echo "==> Production is live at $SHORT."
