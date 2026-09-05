#!/usr/bin/env bash
# Unload optional CC CLI lanes (2026-07-23) — keep offpool + grid poolscan only.
set -euo pipefail
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"
AGENTS=(
  com.demo.aether.premarket-sonnet
  com.demo.aether.sonnet-earnings
  com.demo.aether.paper-crypto-cli
  com.demo.aether.offpool-coach
)
PATTERNS=(
  "premarket_sonnet_daemon.py"
  "sonnet_earnings_daemon.py"
  "paper_crypto_cli_daemon.py"
  "offpool_coach_daemon.py"
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
  rm -f "${plist}" 2>/dev/null || true
done

for pat in "${PATTERNS[@]}"; do
  pkill -f "${pat}" 2>/dev/null || true
done

echo "OK — CC CLI extras stopped (premarket-sonnet, sonnet-earnings, paper-crypto-cli, offpool-coach)"
