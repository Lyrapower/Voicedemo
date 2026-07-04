#!/usr/bin/env bash
# Remove Garden stack LaunchAgents.
set -euo pipefail

DEST="${HOME}/Library/LaunchAgents"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

AGENTS=(
  com.demo.garden.aster8787
  com.demo.garden.telemetry8788
  com.demo.garden.fallback5173
)

for label in "${AGENTS[@]}"; do
  plist="${DEST}/${label}.plist"
  if [[ -f "${plist}" ]]; then
    launchctl bootout "${DOMAIN}" "${plist}" 2>/dev/null || true
    rm -f "${plist}"
    echo "removed ${label}"
  fi
done

echo "Garden LaunchAgents uninstalled."
