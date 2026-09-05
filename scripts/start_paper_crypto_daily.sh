#!/usr/bin/env bash
# Daily crypto momentum signals → paper crypto inbox (09:05 EST weekdays).
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
export PAPER_CRYPTO_ENABLED="${PAPER_CRYPTO_ENABLED:-true}"

PY="${PY:-${NEXUS}/.venv/bin/python}"
# shellcheck source=export_ssl_certs.sh
source "${ROOT}/scripts/aether/export_ssl_certs.sh"
export_ssl_certs "${PY}"

cd "${PAPER}"
exec "${PY}" paper_crypto_daily.py "$@"
