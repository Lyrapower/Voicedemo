#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"
AGENTS="${HOME}/Library/LaunchAgents"

pkill -f "scripts/field_beacon_writer.py" 2>/dev/null || true
pkill -f "scripts/field_now_v1_5.py" 2>/dev/null || true
pkill -f "scripts/field_now_v1_4.py" 2>/dev/null || true
sleep 0.5

install_one() {
  local src="$1" label="$2"
  local dest="${AGENTS}/$(basename "$src")"
  cp "$src" "$dest"
  if launchctl print "${DOMAIN}/${label}" >/dev/null 2>&1; then
    launchctl bootout "${DOMAIN}" "$dest" 2>/dev/null || true
  fi
  launchctl bootstrap "${DOMAIN}" "$dest"
  launchctl enable "${DOMAIN}/${label}"
  launchctl kickstart -k "${DOMAIN}/${label}" || true
  echo "ok ${label}"
}

mkdir -p "$AGENTS"
install_one "${ROOT}/scripts/launchd/com.grid.field-beacon.plist" "com.grid.field-beacon"
install_one "${ROOT}/scripts/launchd/com.grid.field-now.plist" "com.grid.field-now"

sleep 1
curl -sf -m 2 http://127.0.0.1:8795/now | head -3
