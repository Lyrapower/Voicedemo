#!/usr/bin/env bash
# Install pool quant backfill gate only (ensure_pool_scan.py) — no CC / no :8500.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.pool-quant-gate.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.pool-quant-gate.plist"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.pool-quant-gate"

sed -e "s|__DEMO_ROOT__|${ROOT}|g" "${SRC}" >"${DEST}"

if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
  sleep 1
fi

launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"

state="$(launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | grep "state = " | head -1 | sed 's/.*= //' || echo missing)"
echo "pool-quant-gate state=${state}"
echo "OK — calendar trigger ensure_pool_scan (06:35/10:35/12:50 weekdays)"
