#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)/aether_watcher"
NEXUS="$(cd "$(dirname "$0")/../.." && pwd)/aether_nexus"
cd "$ROOT"
export PYTHONPATH="${NEXUS}:${PYTHONPATH:-}"
export GRID_EVENTS="${GRID_EVENTS:-http://127.0.0.1:8501/store/events}"
if [[ -f "${NEXUS}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${NEXUS}/.env"
  set +a
fi
# shellcheck source=ensure_venv.sh
source "$(dirname "$0")/ensure_venv.sh"
ensure_venv "$ROOT"
exec "${ROOT}/.venv/bin/python" aether_watcher.py
