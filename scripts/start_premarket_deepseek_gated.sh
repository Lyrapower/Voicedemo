#!/usr/bin/env bash
# Premarket DeepSeek V4 — 2× daily Ollama cloud, report-only, isolated from Grid/Sonnet.
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

export PREMARKET_DEEPSEEK_WINDOWS="${PREMARKET_DEEPSEEK_WINDOWS:-premarket:06:40,intraday:10:40}"
export PREMARKET_DEEPSEEK_SCHEDULE_TZ="${PREMARKET_DEEPSEEK_SCHEDULE_TZ:-local}"
export PREMARKET_DEEPSEEK_MODEL="${PREMARKET_DEEPSEEK_MODEL:-deepseek-v4-flash:cloud}"
export PREMARKET_DEEPSEEK_TIMEOUT="${PREMARKET_DEEPSEEK_TIMEOUT:-300}"
export OLLAMA_ENDPOINT="${OLLAMA_ENDPOINT:-http://127.0.0.1:11434/api/chat}"

PY="${PY:-${ROOT}/aether_nexus/.venv/bin/python}"
# shellcheck source=export_ssl_certs.sh
source "${ROOT}/scripts/aether/export_ssl_certs.sh"
export_ssl_certs "${PY}"
exec "${PY}" premarket_deepseek_daemon.py "$@"
