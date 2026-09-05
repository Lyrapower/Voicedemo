#!/usr/bin/env bash
# Restart daily-slot LaunchAgents so running loops pick up daemon_schedule.py patches.
set -euo pipefail

LABELS=(
  com.demo.aether.schedule-catchup
  com.demo.aether.post-market-summary
  com.demo.aether.offpool
  com.demo.aether.paper-daily
)

for label in "${LABELS[@]}"; do
  plist="${HOME}/Library/LaunchAgents/${label}.plist"
  if [[ -f "${plist}" ]]; then
    echo "kickstart ${label}"
    launchctl kickstart -k "gui/$(id -u)/${label}" 2>/dev/null || launchctl bootstrap "gui/$(id -u)" "${plist}"
    sleep 2
  else
    echo "skip ${label} (not installed)"
  fi
done

echo "done — schedule catchup watchdog will auto-run any stale lanes"
