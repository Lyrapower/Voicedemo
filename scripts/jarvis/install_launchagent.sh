#!/usr/bin/env bash
# KeepAlive LaunchAgent for Jarvis workbench :8686.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/jarvis/launchd/com.demo.jarvis.platform8686.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.jarvis.platform8686.plist"
LOG="${HOME}/Library/Logs/demo-jarvis"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.jarvis.platform8686"

mkdir -p "${LOG}"
chmod +x "${ROOT}/scripts/jarvis/start_jarvis8686.sh"

sed \
  -e "s|__HOME__|${HOME}|g" \
  -e "s|__DEMO_ROOT__|${ROOT}|g" \
  "${SRC}" >"${DEST}"

if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
  sleep 1
fi

pkill -f "uvicorn app.platform_main:app" 2>/dev/null || true
sleep 1

launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart -k "${DOMAIN}/${LABEL}" || true
sleep 4

code="$(curl -sf --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8686/health 2>/dev/null || echo 000)"
ui="$(curl -sf --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8686/ui/overview 2>/dev/null || echo 000)"
state="$(launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | grep "state = " | head -1 | sed 's/.*= //' || echo missing)"

echo "Jarvis :8686 agent=${state} health=${code} ui=${ui}"
if [[ "${code}" != "200" || "${ui}" != "200" ]]; then
  echo "FAIL — see ${LOG}/platform8686.err.log"
  tail -15 "${LOG}/platform8686.err.log" 2>/dev/null || true
  exit 1
fi
echo "OK — http://127.0.0.1:8686/ui/overview"
