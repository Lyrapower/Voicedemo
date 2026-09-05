#!/usr/bin/env bash
# Off-pool DeepSeek V4 cloud daemon (report-only). CC CLI Sonnet lane retired 2026-07-24.
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

export OFFPOOL_TIME="${OFFPOOL_TIME:-10:50}"
export OFFPOOL_SCHEDULE_TZ="${OFFPOOL_SCHEDULE_TZ:-local}"
export OFFPOOL_CLI_TIMEOUT="${OFFPOOL_CLI_TIMEOUT:-180}"
export OFFPOOL_DEEPSEEK_MODEL="${OFFPOOL_DEEPSEEK_MODEL:-deepseek-v4-flash:cloud}"
export OFFPOOL_DEEPSEEK_TIMEOUT="${OFFPOOL_DEEPSEEK_TIMEOUT:-300}"
export OLLAMA_ENDPOINT="${OLLAMA_ENDPOINT:-http://127.0.0.1:11434/api/chat}"
export CLAUDE_BIN="${CLAUDE_BIN:-${V5}/.tools/node_modules/.bin/claude}"

PY="${PY:-${ROOT}/aether_nexus/.venv/bin/python}"
# shellcheck source=export_ssl_certs.sh
source "${ROOT}/scripts/aether/export_ssl_certs.sh"
export_ssl_certs "${PY}"
exec "${PY}" aether_offpool_daemon.py "$@"
