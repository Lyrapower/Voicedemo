#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.paper-daily.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.paper-daily.plist"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.paper-daily"
mkdir -p "${HOME}/Library/Logs/demo-aether"
chmod +x "${ROOT}/scripts/start_paper_daily_gated.sh"
sed -e "s|__HOME__|${HOME}|g" -e "s|__DEMO_ROOT__|${ROOT}|g" "${SRC}" >"${DEST}"
launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
sleep 1
launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart "${DOMAIN}/${LABEL}" || true
echo "OK — paper daily report @ 16:40"
