#!/usr/bin/env bash
# Aether Nexus Streamlit (:8510). Daemon/dryrun are separate KeepAlive agents.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)/aether_nexus"
cd "$ROOT"
PORT="${STREAMLIT_PORT:-8510}"
# shellcheck source=ensure_venv.sh
source "$(dirname "$0")/ensure_venv.sh"
ensure_venv "$ROOT"
STREAMLIT="${ROOT}/.venv/bin/streamlit"

exec "${STREAMLIT}" run aether_dashboard.py \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.port "${PORT}" \
  --browser.gatherUsageStats false
