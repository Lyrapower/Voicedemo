#!/usr/bin/env bash
# Unload A/B + legacy Sonnet launch agents (see _sealed/ab_2026-07/SEALED.md).
set -euo pipefail
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"
AGENTS=(
  com.demo.aether.premarket-sonnet
  com.demo.aether.premarket-compile
  com.demo.aether.offpool-coach
  com.demo.aether.sonnet-earnings
)
for label in "${AGENTS[@]}"; do
  plist="${HOME}/Library/LaunchAgents/${label}.plist"
  if launchctl print "${DOMAIN}/${label}" >/dev/null 2>&1; then
    launchctl bootout "${DOMAIN}" "${plist}" 2>/dev/null || \
      launchctl bootout "${DOMAIN}/${label}" 2>/dev/null || true
    echo "unloaded ${label}"
  else
    echo "skip ${label} (not loaded)"
  fi
done
