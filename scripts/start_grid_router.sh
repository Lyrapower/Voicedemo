#!/usr/bin/env bash
# Pack 4 Grid Router — standalone (NOT repo/app @ 8787)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export GRID_ROUTER_PORT="${GRID_ROUTER_PORT:-8792}"
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi
exec python3 -m app.main
