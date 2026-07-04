#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

STREAMLIT_PORT="${STREAMLIT_PORT:-8510}"
PY=".venv/bin/python"

start_daemon() {
  if pgrep -f "aether_daemon.py" >/dev/null 2>&1; then
    echo "[daemon] Already running"
    return 0
  fi
  echo "[daemon] Starting aether_daemon.py..."
  nohup "$PY" aether_daemon.py > daemon.log 2>&1 &
  sleep 2
}

start_dashboard() {
  if lsof -i ":${STREAMLIT_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[ui] Streamlit already on port ${STREAMLIT_PORT}"
    return 0
  fi
  echo "[ui] Starting dashboard on port ${STREAMLIT_PORT} (localhost only)..."
  nohup .venv/bin/streamlit run aether_dashboard.py \
    --server.headless true \
    --server.address 127.0.0.1 \
    --server.port "${STREAMLIT_PORT}" \
    > streamlit.log 2>&1 &
  sleep 3
  echo "[ui] http://localhost:${STREAMLIT_PORT}"
}

start_dryrun() {
  if [[ "${DRYRUN_ENABLED:-true}" != "true" ]]; then
    echo "[dryrun] Disabled (set DRYRUN_ENABLED=true to enable)"
    return 0
  fi
  if pgrep -f "aether_dryrun.py" >/dev/null 2>&1; then
    echo "[dryrun] Already running"
    return 0
  fi
  echo "[dryrun] Starting aether_dryrun.py..."
  nohup "$PY" aether_dryrun.py > dryrun.log 2>&1 &
  sleep 1
}

start_daemon
start_dryrun
start_dashboard
echo ""
echo "Aether Nexus R5.4.1 running."
echo "  Scan mode: ${DRYRUN_SCAN_MODE:-pool} (dry run)"
echo "  IB Daemon: ${ROOT}/daemon.log"
echo "  Dry Run:   ${ROOT}/dryrun.log"
echo "  Dashboard: http://localhost:${STREAMLIT_PORT}"
