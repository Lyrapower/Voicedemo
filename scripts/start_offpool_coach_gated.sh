#!/usr/bin/env bash
# DISABLED 2026-07-23 — offpool Fable coach CC CLI lane removed.
echo "offpool-coach terminated 2026-07-23" >&2
exit 0
# Off-pool Fable coach — PREMARKET trial, CC CLI read-only, referee-gated.
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
export PREMARKET_WINDOW_PST="${PREMARKET_WINDOW_PST:-06:20}"
export OFFPOOL_COACH_CLI_MODEL="${OFFPOOL_COACH_CLI_MODEL:-claude-fable-5}"
PY="${PY:-${ROOT}/aether_nexus/.venv/bin/python}"
# shellcheck source=export_ssl_certs.sh
source "${ROOT}/scripts/aether/export_ssl_certs.sh"
export_ssl_certs "${PY}"
exec "${PY}" offpool_coach_daemon.py "$@"
