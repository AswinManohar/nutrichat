#!/usr/bin/env bash
#
# prod-checks.sh — code and security checks a commit must pass before it can
# go to the `production` branch.
#
# Runs in a throwaway git worktree checked out at the commit, so your working
# tree (and any uncommitted edits) is never touched. On success it records a
# pass marker that the `pre-push` hook requires for pushes to `production`.
#
# Usage:
#   scripts/prod-checks.sh [<commit>]      # default: HEAD
#
# Checks (any failure blocks):
#   code      ruff (no NEW findings in changed .py files), backend pytest,
#             frontend tests + typecheck/build
#   database  every Alembic migration in the commit is already applied to the
#             production database (migrations are applied manually; see
#             docs/deployment/deploy-guide.md)
#   security  gitleaks on the commits being shipped; bandit (high severity);
#             pip-audit and npm audit — only vulnerabilities NOT listed in
#             security/audit-baseline.json block
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
GIT_COMMON="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
MARKER_DIR="$GIT_COMMON/prod-checks"
GITLEAKS="$(command -v gitleaks || echo "$HOME/.local/bin/gitleaks")"
# Known offline failure: calls real Gemini with a dummy key.
DESELECT=(--deselect tests/test_e2e_meals.py::test_chat_history_isolation)

SHA="$(git rev-parse --verify "${1:-HEAD}^{commit}")"
SHORT="${SHA:0:8}"
git fetch -q origin production
BASE="$(git rev-parse origin/production)"

WORK="$(mktemp -d -t prodcheck-XXXXXX)"
LOG_DIR="$WORK/logs"
mkdir -p "$LOG_DIR"
cleanup() { git worktree remove --force "$WORK/tree" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

FAILED=()
step() { printf '\n==> %s\n' "$1"; }
pass() { printf '    PASS  %s\n' "$1"; }
fail() { printf '    FAIL  %s\n' "$1"; FAILED+=("$1"); }

step "Checking $SHORT (production is at ${BASE:0:8}, $(git rev-list --count "$BASE..$SHA") commits ahead)"
if ! git merge-base --is-ancestor "$BASE" "$SHA"; then
  echo "ERROR: $SHORT does not contain origin/production; promotion must be a fast-forward." >&2
  exit 1
fi
git worktree add -q --detach "$WORK/tree" "$SHA"
cd "$WORK/tree"

# --- code ---------------------------------------------------------------------
step "Python environment (uv sync --frozen)"
if uv sync -q --frozen >"$LOG_DIR/uv.log" 2>&1; then pass "uv sync"; else fail "uv sync (see uv.log)"; fi

step "Ruff: no new findings in changed Python files"
NEW_LINT=0
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  after=$(uv run -q ruff check --output-format concise "$f" 2>/dev/null | grep -c ':[0-9]*:[0-9]*:' || true)
  before=$(git show "$BASE:$f" 2>/dev/null \
    | uv run -q ruff check --output-format concise --stdin-filename "$f" - 2>/dev/null \
    | grep -c ':[0-9]*:[0-9]*:' || true)
  if (( after > before )); then
    echo "    $f: $before -> $after findings"; NEW_LINT=1
  fi
done < <(git diff --name-only --diff-filter=AM "$BASE" "$SHA" -- '*.py')
(( NEW_LINT == 0 )) && pass "ruff" || fail "ruff (new findings above)"

step "Backend tests (pytest)"
# Some tests need the local docker Postgres (:5411) and Redis; never prod.
docker start nutrichat-pg nutrichat-redis >/dev/null 2>&1 \
  && for _ in $(seq 1 20); do pg_isready -q -h 127.0.0.1 -p 5411 && break; sleep 1; done \
  || echo "    (docker containers not started; DB-dependent tests may fail)"
if env -u DATABASE_URL PYTHONPATH=src uv run -q pytest -q -p no:cacheprovider \
    "${DESELECT[@]}" >"$LOG_DIR/pytest.log" 2>&1; then
  pass "pytest ($(tail -1 "$LOG_DIR/pytest.log"))"
else
  tail -15 "$LOG_DIR/pytest.log"; fail "pytest"
fi

step "Frontend tests and build"
if (cd frontend && npm ci --silent --no-audit --no-fund >"$LOG_DIR/npm-ci.log" 2>&1); then
  if (cd frontend && npm test --silent >"$LOG_DIR/vitest.log" 2>&1); then pass "vitest"
  else tail -15 "$LOG_DIR/vitest.log"; fail "vitest"; fi
  # Typecheck + bundle only; the real build runs on Netlify with prod env vars.
  if (cd frontend && npm run build --silent >"$LOG_DIR/build.log" 2>&1); then pass "tsc + vite build"
  else tail -15 "$LOG_DIR/build.log"; fail "frontend build"; fi
else
  tail -10 "$LOG_DIR/npm-ci.log"; fail "npm ci"
fi

# --- database -----------------------------------------------------------------
step "Migrations already applied to production"
PROD_ENV="$REPO_ROOT/.env"
if [[ ! -f "$PROD_ENV" ]]; then
  fail "migrations: no $PROD_ENV with the production DATABASE_URL"
else
  HEADS=$(PYTHONPATH=src DATABASE_URL=postgresql+asyncpg://x@localhost/x \
    uv run -q alembic heads 2>/dev/null | awk '{print $1}' | sort | tr '\n' ' ')
  PROD=$(uv run -q --env-file "$PROD_ENV" python - <<'PY' 2>"$LOG_DIR/alembic-prod.log" | sort | tr '\n' ' '
import asyncio, os
import asyncpg
async def main():
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)  # read-only: one SELECT
    try:
        for row in await conn.fetch("SELECT version_num FROM alembic_version"):
            print(row["version_num"])
    finally:
        await conn.close()
asyncio.run(main())
PY
)
  if [[ -z "$PROD" ]]; then
    tail -3 "$LOG_DIR/alembic-prod.log"; fail "migrations: could not read production alembic_version"
  elif [[ "$HEADS" == "$PROD" ]]; then
    pass "alembic head(s) $HEADS match production"
  else
    echo "    code head(s): $HEADS"; echo "    production:   $PROD"
    fail "migrations: apply to Supabase first (docs/deployment/deploy-guide.md)"
  fi
fi

# --- security -----------------------------------------------------------------
step "Secrets in the commits being shipped (gitleaks)"
if [[ ! -x "$GITLEAKS" ]]; then
  fail "gitleaks not installed (see docs/deployment/deploy-guide.md)"
elif "$GITLEAKS" git --log-opts="$BASE..$SHA" --no-banner --redact \
    --exit-code 1 . >"$LOG_DIR/gitleaks.log" 2>&1; then
  pass "gitleaks: no leaks"
else
  cat "$LOG_DIR/gitleaks.log"; fail "gitleaks: possible secret committed"
fi

step "Python code security (bandit, high severity)"
if uvx -q bandit -r src/backend -lll -q >"$LOG_DIR/bandit.log" 2>&1; then
  pass "bandit: no high-severity issues"
else
  cat "$LOG_DIR/bandit.log"; fail "bandit"
fi

step "Dependency vulnerabilities (pip-audit, npm audit) vs security/audit-baseline.json"
uv export -q --frozen --no-dev --no-hashes --format requirements-txt >"$WORK/req.txt"
uvx -q pip-audit -r "$WORK/req.txt" --no-deps --disable-pip --format json \
  -o "$WORK/pip-audit.json" >"$LOG_DIR/pip-audit.log" 2>&1 || true
(cd frontend && npm audit --omit=dev --json >"$WORK/npm-audit.json" 2>/dev/null) || true
if python3 - "$WORK/pip-audit.json" "$WORK/npm-audit.json" security/audit-baseline.json <<'PY'
import json, sys
pip_path, npm_path, base_path = sys.argv[1:4]
base = json.load(open(base_path))
try:
    pa = json.load(open(pip_path))
    pip = {f"{d['name']}:{v['id']}" for d in pa["dependencies"] for v in d.get("vulns", [])}
except (OSError, ValueError, KeyError):
    print("    pip-audit produced no report"); sys.exit(1)
npm_report = json.load(open(npm_path))
npm = {
    f"{name}:{via['source']}"
    for name, v in npm_report.get("vulnerabilities", {}).items()
    if v.get("severity") in ("high", "critical")
    for via in v.get("via", []) if isinstance(via, dict)
}
new_pip = sorted(pip - set(base["pip_audit"]))
new_npm = sorted(npm - set(base["npm_audit"]))
print(f"    known (baselined): {len(pip & set(base['pip_audit']))} Python, "
      f"{len(npm & set(base['npm_audit']))} npm high/critical")
for item in new_pip + new_npm:
    print(f"    NEW  {item}")
sys.exit(1 if new_pip or new_npm else 0)
PY
then pass "no new dependency vulnerabilities"
else fail "new dependency vulnerabilities (upgrade, or baseline with a reason)"
fi

# --- result -------------------------------------------------------------------
cd "$REPO_ROOT"
echo
if (( ${#FAILED[@]} )); then
  echo "==> BLOCKED: ${#FAILED[@]} check(s) failed for $SHORT:"
  printf '      - %s\n' "${FAILED[@]}"
  exit 1
fi
mkdir -p "$MARKER_DIR"
{ date -u +%FT%TZ; echo "base $BASE"; } >"$MARKER_DIR/$SHA"
echo "==> ALL CHECKS PASSED for $SHORT — recorded in $MARKER_DIR/$SHA"
