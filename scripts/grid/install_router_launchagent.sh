#!/usr/bin/env bash
# Install Grid Router :8500 (Grid+CC scan dependency)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST_SRC="$REPO/scripts/grid/launchd/com.grid.router.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.grid.router.plist"
UID_NUM="$(id -u)"

chmod +x "$REPO/scripts/grid/start_router.sh"
cp "$PLIST_SRC" "$PLIST_DEST"
if launchctl print "gui/$UID_NUM/com.grid.router" >/dev/null 2>&1; then
  launchctl bootout "gui/$UID_NUM/com.grid.router" 2>/dev/null || true
fi
launchctl bootstrap "gui/$UID_NUM" "$PLIST_DEST" 2>/dev/null || true
launchctl kickstart -k "gui/$UID_NUM/com.grid.router" 2>/dev/null || launchctl bootstrap "gui/$UID_NUM" "$PLIST_DEST"
sleep 2
curl -sf "http://127.0.0.1:8500/health" >/dev/null && echo "OK router :8500" || { echo "FAIL router health"; exit 1; }
