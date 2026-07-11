#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

BASE_SHA="1693b01907bac827c3861374ea581e6cb629d3c7"
WORKTREE="/tmp/psychoanalyst-phase1-base"

cleanup() {
  if git worktree list | grep -q "$WORKTREE"; then
    git worktree remove --force "$WORKTREE"
  fi
}
trap cleanup EXIT

git worktree add "$WORKTREE" "$BASE_SHA" >/dev/null

echo "# Phase 1 start (worktree ${BASE_SHA})"
docker compose run --rm -v "${WORKTREE}:/worktree:ro" api \
  python scripts/measure_codebase.py --root /worktree --format markdown

echo
echo "# Phase 1 completion (current tree)"
docker compose run --rm api python scripts/measure_codebase.py --format markdown
