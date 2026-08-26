#!/bin/bash
# docker-watchdog — keep Docker Desktop daemon up.
# Checks `docker info`; if down, `open -a Docker` with a cooldown so we don't
# spam launches while Docker Desktop is mid-startup (takes ~20-40s to be ready).
# Idempotent: `open -a Docker` on an already-running app is a no-op focus.
set -u

LOG="$HOME/Library/Logs/demo-grid/docker-watchdog.log"
STATE="/tmp/grid_docker_watchdog_state"
COOLDOWN_S=90
mkdir -p "$(dirname "$LOG")"
ts(){ date '+%Y-%m-%d %H:%M:%S'; }

# healthy daemon → clear state, done
if docker info >/dev/null 2>&1; then
  rm -f "$STATE" 2>/dev/null
  exit 0
fi

# daemon down — respect cooldown (avoid re-launch spam during slow startup)
now=$(date +%s)
last=0; [ -f "$STATE" ] && last=$(cat "$STATE" 2>/dev/null) || true
if [ $((now-last)) -lt $COOLDOWN_S ]; then
  exit 0
fi

echo "$now" > "$STATE"
echo "[$(ts)] docker daemon down — open -a Docker" >>"$LOG"
open -a Docker
