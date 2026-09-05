#!/usr/bin/env bash
# Install off-pool CC CLI Sonnet LaunchAgent (report-only, 17:15 EST default).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.offpool.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.offpool.plist"
LOG="${HOME}/Library/Logs/demo-aether"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.offpool"

mkdir -p "${LOG}"
chmod +x "${ROOT}/scripts/start_offpool_gated.sh"

echo "=== referee gate (fail closed) ==="
cd "${ROOT}/aster_grid_v5"
# shellcheck source=/dev/null
source env.sh
unset ASTER_ALLOW_FALLBACK_VERIFIER
export CC_CLI_EXECUTION_FROZEN=1
./referee_selftest.sh

SSL_CERT="$(python3 -m certifi 2>/dev/null || "${ROOT}/aether_nexus/.venv/bin/python" -m certifi 2>/dev/null || true)"
sed \
  -e "s|__HOME__|${HOME}|g" \
  -e "s|__DEMO_ROOT__|${ROOT}|g" \
  -e "s|__SSL_CERT_FILE__|${SSL_CERT}|g" \
  "${SRC}" >"${DEST}"

if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
  sleep 1
fi

pkill -f "aether_offpool_daemon.py" 2>/dev/null || true
sleep 1

launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart "${DOMAIN}/${LABEL}" || true
sleep 3

state="$(launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | grep "state = " | head -1 | sed 's/.*= //' || echo missing)"
pid="$(pgrep -f 'aether_offpool_daemon.py --loop' | head -1 || true)"

echo "offpool agent state=${state} pid=${pid:-none}"
if [[ "${state}" != "running" || -z "${pid}" ]]; then
  echo "FAIL — see ${LOG}/offpool.err.log"
  tail -20 "${LOG}/offpool.err.log" 2>/dev/null || true
  exit 1
fi

echo "OK — offpool daemon (DeepSeek V4 cloud only, report-only)"
