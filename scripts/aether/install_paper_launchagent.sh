#!/usr/bin/env bash
# Install Aether paper loop LaunchAgent ($1000 mock, Grid/Aster scan signals).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.paper.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.paper.plist"
LOG="${HOME}/Library/Logs/demo-aether"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.paper"

mkdir -p "${LOG}"
chmod +x "${ROOT}/scripts/start_paper_gated.sh"

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

pkill -f "paper_daemon.py --loop" 2>/dev/null || true
sleep 1

launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart "${DOMAIN}/${LABEL}" || true
sleep 3

state="$(launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | grep "state = " | head -1 | sed 's/.*= //' || echo missing)"
pid="$(pgrep -f 'paper_daemon.py --loop' | head -1 || true)"

echo "paper agent state=${state} pid=${pid:-none}"
if [[ "${state}" != "running" || -z "${pid}" ]]; then
  echo "FAIL — see ${LOG}/paper.err.log"
  tail -20 "${LOG}/paper.err.log" 2>/dev/null || true
  exit 1
fi

echo "OK — paper daemon (Grid/Aster scan → mock wallet, broker_execution=false)"
bash "${ROOT}/scripts/aether/install_paper_crypto_daily_launchagent.sh"
bash "${ROOT}/scripts/aether/install_paper_daily_launchagent.sh"
