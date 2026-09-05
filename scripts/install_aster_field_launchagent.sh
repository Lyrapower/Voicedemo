#!/usr/bin/env bash
# Install ASTER FIELD bridge LaunchAgent (:8790) — launchctl only, no port kill.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/scripts/garden/launchd/com.demo.field.bridge8790.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.field.bridge8790.plist"
LOG_GRID="${HOME}/Library/Logs/demo-grid"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"
LABEL="com.demo.field.bridge8790"

chmod +x "${ROOT}/scripts/start_aster_field_8790.sh"
mkdir -p "${LOG_GRID}"

python3 -m pip install -q -r "${ROOT}/aster-field/backend/requirements.txt"

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
sleep 2

echo "=== ASTER FIELD :8790 ==="
curl -sf http://127.0.0.1:8790/health | python3 -m json.tool || {
  echo "FAIL — see ${LOG_GRID}/field8790.err.log"
  tail -15 "${LOG_GRID}/field8790.err.log" 2>/dev/null || true
  exit 1
}
echo ""
echo "Open: http://127.0.0.1:8790/"
echo "Restart: launchctl kickstart -k \"gui/\$(id -u)/${LABEL}\""
