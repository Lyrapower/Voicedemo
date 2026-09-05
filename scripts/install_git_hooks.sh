#!/usr/bin/env bash
# Install repo git hooks (pre-commit P0 guard). Idempotent.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_SRC="$ROOT/scripts/git-hooks/pre-commit"
HOOK_DST="$ROOT/.git/hooks/pre-commit"

if [[ ! -d "$ROOT/.git" ]]; then
  echo "FAIL: not a git repo: $ROOT"
  exit 1
fi
chmod +x "$HOOK_SRC"
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"
echo "OK: installed $HOOK_DST"
echo "  runs: grid_infrastructure_guard.py check-staged + verify_grid_chain_integrity.sh"
