#!/usr/bin/env bash
# Auto catch-up for missed daily Aether slots — no referee gate (read-only health + --once).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${ROOT}/aether_nexus"

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

export CC_CLI_EXECUTION_FROZEN=1
export GRID_EVENTS="${GRID_EVENTS:-http://127.0.0.1:8501/store/events}"
# Fable offpool_coach sealed/retired 2026-07-23 — missing coach must not fail whole stack QA
export OFFPOOL_COACH_STATUS="${OFFPOOL_COACH_STATUS:-retired}"
export OFFPOOL_COACH_REQUIRED="${OFFPOOL_COACH_REQUIRED:-0}"

PY="${PY:-${ROOT}/aether_nexus/.venv/bin/python}"
# shellcheck source=export_ssl_certs.sh
source "${ROOT}/scripts/aether/export_ssl_certs.sh"
export_ssl_certs "${PY}"
exec "${PY}" schedule_catchup_daemon.py "$@"
