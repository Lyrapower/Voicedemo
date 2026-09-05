#!/usr/bin/env bash
# Install Aster diary LaunchAgent (daily 22:30 local — no KeepAlive, ops only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aster/launchd/com.demo.aster.diary.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aster.diary.plist"
LOG="${HOME}/Library/Logs/demo-aster"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aster.diary"

mkdir -p "${LOG}" "${ROOT}/aster-diary/diary"
chmod +x "${ROOT}/scripts/aster/start_aster_diary.sh"
chmod 700 "${ROOT}/aster-diary/diary" 2>/dev/null || true

sed \
  -e "s|__HOME__|${HOME}|g" \
  -e "s|__DEMO_ROOT__|${ROOT}|g" \
  "${SRC}" >"${DEST}"

if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
  sleep 1
fi

launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"

echo "=== smoke run (one entry today) ==="
bash "${ROOT}/scripts/aster/start_aster_diary.sh" || true

echo ""
echo "=== verify manifest ==="
bash "${ROOT}/scripts/aster/start_aster_diary.sh" --verify

launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | rg "state =|path =" | head -2 || true
echo ""
echo "OK — diary at ${ROOT}/aster-diary/diary/ (0600)"
echo "Schedule: daily 22:30 local · logs ${LOG}/diary.*.log"
echo "Manual: bash scripts/aster/start_aster_diary.sh"
