#!/usr/bin/env bash
# Install GRID Workbench UI LaunchAgent (:8515) — launchctl only, no port kill.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/scripts/garden/launchd/com.demo.workbench.ui8515.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.workbench.ui8515.plist"
LOG_GRID="${HOME}/Library/Logs/demo-grid"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"
LABEL="com.demo.workbench.ui8515"

chmod +x "${ROOT}/scripts/start_workbench_8515.sh"
mkdir -p "${LOG_GRID}"

python3 -m pip install -q -r "${ROOT}/aster-field/backend/requirements.txt"

if command -v lsof >/dev/null 2>&1; then
  pids="$(lsof -tiTCP:8515 -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping stale listener(s) on :8515 (${pids})"
    kill ${pids} 2>/dev/null || true
    sleep 1
  fi
fi

sed \
  -e "s|__HOME__|${HOME}|g" \
  -e "s|__DEMO_ROOT__|${ROOT}|g" \
  "${SRC}" > "${DEST}"

if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
  sleep 1
fi

launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart -k "${DOMAIN}/${LABEL}" || true
sleep 3

echo "=== GRID Workbench UI :8515 ==="
curl -sf http://127.0.0.1:8515/health | python3 -m json.tool || {
  echo "FAIL — see ${LOG_GRID}/workbench8515.err.log"
  tail -15 "${LOG_GRID}/workbench8515.err.log" 2>/dev/null || true
  exit 1
}
echo ""
echo "Open: http://127.0.0.1:8515/grid_workbench_b11.html"
echo "Restart: launchctl kickstart -k \"gui/\$(id -u)/${LABEL}\""
