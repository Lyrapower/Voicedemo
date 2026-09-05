#!/usr/bin/env bash
# DISABLED 2026-07-23 — sonnet earnings CC CLI lane removed.
echo "sonnet-earnings terminated 2026-07-23" >&2
exit 0
# Sonnet earnings lane — report-only, CC CLI, referee-gated.
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
export SONNET_EARNINGS_CLI_MODEL="${SONNET_EARNINGS_CLI_MODEL:-claude-sonnet-4-6}"
PY="${PY:-${ROOT}/aether_nexus/.venv/bin/python}"
# shellcheck source=export_ssl_certs.sh
source "${ROOT}/scripts/aether/export_ssl_certs.sh"
export_ssl_certs "${PY}"
exec "${PY}" sonnet_earnings_daemon.py "$@"
