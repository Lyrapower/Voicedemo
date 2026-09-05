#!/usr/bin/env bash
# Install BFS watchdog LaunchAgent (09:55 / 15:45 ET weekdays).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.bfs-watchdog.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.bfs-watchdog.plist"
LOG="${HOME}/Library/Logs/demo-aether"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.bfs-watchdog"

mkdir -p "${LOG}"
chmod +x "${ROOT}/scripts/start_bfs_watchdog.sh"
python3 -m py_compile "${ROOT}/aether_nexus/bfs_watchdog.py"

sed \
  -e "s|__HOME__|${HOME}|g" \
  -e "s|__DEMO_ROOT__|${ROOT}|g" \
  "${SRC}" >"${DEST}"

plutil -lint "${DEST}"

if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
  sleep 1
fi

launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"

state="$(launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | grep "state = " | head -1 | sed 's/.*= //' || echo missing)"
echo "bfs-watchdog state=${state}"
echo "OK — calendar 06:55/12:45 PT · log ${LOG}/bfs_watchdog.log"
echo "C4 log ${LOG}/nexus-dryrun.err.log · marker 'BFS sp500 scan finished'"
echo "LLM http://127.0.0.1:8501/v1/chat/completions · model demo/aster"
