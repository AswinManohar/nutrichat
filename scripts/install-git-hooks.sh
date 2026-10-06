#!/usr/bin/env bash
# Install the repo's git hooks (shared by every worktree of this clone).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
HOOKS="$(git rev-parse --git-common-dir)/hooks"
for hook in scripts/git-hooks/*; do
  name="$(basename "$hook")"
  if [[ -e "$HOOKS/$name" && ! -L "$HOOKS/$name" ]]; then
    echo "skip $name: $HOOKS/$name exists and is not ours" >&2; continue
  fi
  ln -sf "$(pwd)/$hook" "$HOOKS/$name"
  echo "installed $name -> $hook"
done
