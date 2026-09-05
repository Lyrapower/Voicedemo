#!/usr/bin/env bash
# BFS watchdog one-shot — env from aether_nexus/.env + fixed paths (no secrets in plist).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AETHER="${ROOT}/aether_nexus"
LOG_DIR="${HOME}/Library/Logs/demo-aether"
mkdir -p "${LOG_DIR}"
cd "${AETHER}"
# shellcheck source=ensure_venv.sh
source "$(dirname "$0")/aether/ensure_venv.sh"
ensure_venv "${AETHER}" 2>/dev/null || true
# shellcheck source=export_ssl_certs.sh
source "$(dirname "$0")/aether/export_ssl_certs.sh"
PY="${AETHER}/.venv/bin/python"
if [[ -x "${PY}" ]]; then
  export_ssl_certs "${PY}"
else
  PY="$(command -v python3)"
fi
if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi
export WATCHDOG_STORE_DB="${WATCHDOG_STORE_DB:-${ROOT}/grid-sovereign-runtime/data/grid_store.db}"
export WATCHDOG_HEARTBEAT="${WATCHDOG_HEARTBEAT:-${AETHER}/dryrun_state/heartbeat.json}"
export WATCHDOG_DRYRUN_LOG="${WATCHDOG_DRYRUN_LOG:-${LOG_DIR}/nexus-dryrun.err.log}"
export WATCHDOG_TG_OK_MARKER="${WATCHDOG_TG_OK_MARKER:-BFS sp500 scan finished}"
export WATCHDOG_LLM_URL="${WATCHDOG_LLM_URL:-http://127.0.0.1:8501/v1/chat/completions}"
export WATCHDOG_LLM_MODEL="${WATCHDOG_LLM_MODEL:-demo/aster}"
export GRID_EVENTS="${GRID_EVENTS:-http://127.0.0.1:8501/store/events}"
export WATCHDOG_STATE="${WATCHDOG_STATE:-${AETHER}/watchdog_state.json}"
exec "${PY}" "${AETHER}/bfs_watchdog.py"
