#!/usr/bin/env bash
# DISABLED 2026-07-23 — premarket Sonnet CC CLI lane removed; pool via grid poolscan only.
echo "premarket-sonnet terminated 2026-07-23" >&2
exit 0
# Premarket Sonnet compile via CC CLI — report-only, referee-gated. Daily 06:40 local.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V5="${ROOT}/aster_grid_v5"

cd "${V5}"
# shellcheck source=/dev/null
source env.sh
unset ASTER_ALLOW_FALLBACK_VERIFIER
export CC_CLI_EXECUTION_FROZEN=1
./referee_selftest.sh

cd "${ROOT}/aether_nexus"
if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi
export GRID_EVENTS="${GRID_EVENTS:-http://127.0.0.1:8501/store/events}"
export PREMARKET_SONNET_CLI_MODEL="${PREMARKET_SONNET_CLI_MODEL:-claude-sonnet-4-6}"
PY="${PY:-${ROOT}/aether_nexus/.venv/bin/python}"
# shellcheck source=export_ssl_certs.sh
source "${ROOT}/scripts/aether/export_ssl_certs.sh"
export_ssl_certs "${PY}"
exec "${PY}" premarket_sonnet_daemon.py "$@"
