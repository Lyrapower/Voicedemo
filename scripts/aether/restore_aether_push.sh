#!/usr/bin/env bash
# Restore Aether scan daemons + Telegram/post-market notifications + app store feed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOMAIN="gui/$(id -u)"

echo "=== 1/3 Scan + watcher LaunchAgents ==="
bash "${ROOT}/scripts/aether/install_launchagents.sh"

echo ""
echo "=== 2/3 Post-market (Telegram + aether_brief) ==="
bash "${ROOT}/scripts/aether/install_post_market_summary_launchagent.sh"

echo ""
echo "=== 3/3 Verify ==="
launchctl list 2>/dev/null | grep -E 'aether\.(nexus-daemon|nexus-dryrun|watcher-daemon|post-market)' || true

if [[ -f "${ROOT}/aether_nexus/.env" ]]; then
  if grep -qE '^TELEGRAM_BOT_TOKEN=.+' "${ROOT}/aether_nexus/.env" 2>/dev/null; then
    echo "OK  TELEGRAM_BOT_TOKEN present in aether_nexus/.env"
  else
    echo "WARN TELEGRAM_BOT_TOKEN missing — add to ${ROOT}/aether_nexus/.env"
  fi
else
  echo "WARN no aether_nexus/.env — copy from .env.example"
fi

echo ""
echo "App: https://cicimacbook-air.tail76db5b.ts.net/app/aether.html"
echo "Post-market fires 16:35 EST · scans per dryrun schedule in aether_dryrun.py"
