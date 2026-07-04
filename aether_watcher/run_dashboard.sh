#!/usr/bin/env bash
# Aether Watcher Streamlit dashboard (:8520 localhost only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PORT="${WATCHER_DASHBOARD_PORT:-8520}"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/streamlit run watcher_dashboard.py \
  --server.address 127.0.0.1 \
  --server.port "${PORT}" \
  --browser.gatherUsageStats false
