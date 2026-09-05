#!/usr/bin/env bash
# DISABLED 2026-07-23 — crypto paper CC CLI lane removed.
echo "paper-crypto-cli terminated 2026-07-23" >&2
exit 0
# Crypto paper CC CLI (sonnet-4.6) — A/B treatment lane, referee-gated.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V5="${ROOT}/aster_grid_v5"
PAPER="${ROOT}/aether-paper"

cd "${V5}"
# shellcheck source=/dev/null
source env.sh
unset ASTER_ALLOW_FALLBACK_VERIFIER
export CC_CLI_EXECUTION_FROZEN=1
./referee_selftest.sh

cd "${PAPER}"
export GRID_EVENTS="${GRID_EVENTS:-http://127.0.0.1:8501/store/events}"
export CLAUDE_BIN="${CLAUDE_BIN:-${V5}/.tools/node_modules/.bin/claude}"
export CRYPTO_PAPER_CLI_MODEL="${CRYPTO_PAPER_CLI_MODEL:-claude-sonnet-4-6}"
export CRYPTO_PAPER_CLI_LANE="${CRYPTO_PAPER_CLI_LANE:-sonnet-4.6}"

PY="${PY:-${ROOT}/aether_nexus/.venv/bin/python}"
# shellcheck source=export_ssl_certs.sh
source "${ROOT}/scripts/aether/export_ssl_certs.sh"
export_ssl_certs "${PY}"
exec "${PY}" paper_crypto_cli_daemon.py "$@"
