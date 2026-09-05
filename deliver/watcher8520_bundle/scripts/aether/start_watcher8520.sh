#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)/aether_watcher"
cd "$ROOT"
PORT="${WATCHER_DASHBOARD_PORT:-8520}"
# shellcheck source=ensure_venv.sh
source "$(dirname "$0")/ensure_venv.sh"
ensure_venv "$ROOT"
STREAMLIT="${ROOT}/.venv/bin/streamlit"

exec "${STREAMLIT}" run watcher_dashboard.py \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.port "${PORT}" \
  --browser.gatherUsageStats false
