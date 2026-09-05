#!/usr/bin/env bash
# Aether paper loop — Grid/Aster scan → $1000 mock wallet (no broker).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NEXUS="${ROOT}/aether_nexus"
PAPER="${ROOT}/aether-paper"

cd "${NEXUS}"
if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

export GRID_EVENTS="${GRID_EVENTS:-http://127.0.0.1:8501/store/events}"
export PAPER_LOOP_ENABLED="${PAPER_LOOP_ENABLED:-true}"
export PAPER_CRYPTO_ENABLED="${PAPER_CRYPTO_ENABLED:-true}"
export PAPER_ASSET_CLASS="${PAPER_ASSET_CLASS:-equity}"
export PAPER_TICK_SEC="${PAPER_TICK_SEC:-120}"
export TRADING_START="${TRADING_START:-10:00}"
export TRADING_END="${TRADING_END:-15:00}"

PY="${PY:-${NEXUS}/.venv/bin/python}"
# shellcheck source=export_ssl_certs.sh
source "${ROOT}/scripts/aether/export_ssl_certs.sh"
export_ssl_certs "${PY}"

cd "${PAPER}"
exec "${PY}" paper_daemon.py "$@"
