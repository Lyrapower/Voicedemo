#!/usr/bin/env bash
# Install schedule catch-up watchdog (KeepAlive — auto-runs missed daily lanes).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.schedule-catchup.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.schedule-catchup.plist"
LOG="${HOME}/Library/Logs/demo-aether"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.schedule-catchup"

mkdir -p "${LOG}"
chmod +x "${ROOT}/scripts/aether/start_schedule_catchup.sh"

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

launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart -k "${DOMAIN}/${LABEL}" || true
sleep 2

pid="$(pgrep -f 'schedule_catchup_daemon.py --loop' | head -1 || true)"
echo "schedule-catchup pid=${pid:-none}"
if [[ -z "${pid}" ]]; then
  echo "FAIL — see ${LOG}/schedule-catchup.err.log"
  tail -20 "${LOG}/schedule-catchup.err.log" 2>/dev/null || true
  exit 1
fi
echo "OK — schedule catchup watchdog (poll 120s, grace 3m)"
