#!/usr/bin/env bash
# DISABLED 2026-07-23 — premarket Sonnet CC CLI removed.
echo "premarket-sonnet install disabled 2026-07-23" >&2
exit 0
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.premarket-sonnet.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.premarket-sonnet.plist"
LOG="${HOME}/Library/Logs/demo-aether"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.premarket-sonnet"

mkdir -p "${LOG}"
chmod +x "${ROOT}/scripts/start_premarket_sonnet_gated.sh"

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
launchctl kickstart "${DOMAIN}/${LABEL}" || true
sleep 2
state="$(launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | grep "state = " | head -1 | sed 's/.*= //' || echo missing)"
echo "premarket-sonnet agent state=${state}"
