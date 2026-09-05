#!/usr/bin/env bash
# Stop + uninstall LaunchAgents not in the current authorized stack.
# KEEP: 8510, 8520, 5173 (user request), gateway, field, post-market, egress, diary.
set -euo pipefail
DOMAIN="gui/$(id -u)"
DEST="${HOME}/Library/LaunchAgents"

REMOVE=(
  com.demo.aether.nexus-daemon
  com.demo.aether.nexus-dryrun
  com.demo.aether.watcher-daemon
  com.demo.garden.aster8787
  com.demo.garden.telemetry8788
  com.demo.jarvis.platform8686
  com.demo.lms.aster-dev
)

for label in "${REMOVE[@]}"; do
  plist="${DEST}/${label}.plist"
  if [[ -f "$plist" ]]; then
    launchctl bootout "${DOMAIN}" "$plist" 2>/dev/null || true
    rm -f "$plist"
    echo "removed $label"
  else
    echo "skip (no plist) $label"
  fi
done

pkill -f "http.server 8891" 2>/dev/null || true

echo ""
echo "=== kept by policy: 8510 8520 5173 + core stack ==="
launchctl list 2>/dev/null | rg 'com\.demo\.(grid\.gateway8501|field\.bridge8790|workbench\.ui8515|aether\.post-market|grid\.egress|aster\.diary|aether\.nexus8510|aether\.watcher8520|garden\.fallback5173)' || true
echo ""
echo "=== listening ==="
for p in 5173 8501 8502 8503 8686 8787 8790 8891 8510 8520; do
  lsof -iTCP:$p -sTCP:LISTEN 2>/dev/null | tail -1 | awk -v p=$p '{if(NF) print ":"p, $0; else print ":"p, "(free)"}'
done
