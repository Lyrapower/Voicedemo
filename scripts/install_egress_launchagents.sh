#!/usr/bin/env bash
# Install egress LaunchAgent (8502 ARK only). Anthropic :8503 retired — use CC CLI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${HOME}/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
KEY="${EGRESS_SMOKE_KEY:-egress-smoke-deny}"
mkdir -p "${HOME}/Library/Logs/demo-grid"
chmod +x "${ROOT}/scripts/start_egress_ark.sh"
port=8502
src="${ROOT}/scripts/garden/launchd/com.demo.grid.egress${port}.plist"
out="${DEST}/com.demo.grid.egress${port}.plist"
sed -e "s|__HOME__|${HOME}|g" -e "s|__DEMO_ROOT__|${ROOT}|g" -e "s|__EGRESS_SMOKE_KEY__|${KEY}|g" "$src" >"$out"
label="com.demo.grid.egress${port}"
launchctl bootout "${DOMAIN}" "$out" 2>/dev/null || true
launchctl bootstrap "${DOMAIN}" "$out"
launchctl enable "${DOMAIN}/${label}"
launchctl kickstart "${DOMAIN}/${label}" || true
# Retire legacy :8503 agent if present
legacy="${DEST}/com.demo.grid.egress8503.plist"
if [[ -f "$legacy" ]]; then
  launchctl bootout "${DOMAIN}" "$legacy" 2>/dev/null || true
  rm -f "$legacy"
fi
sleep 2
pgrep -fl egress.py || true
