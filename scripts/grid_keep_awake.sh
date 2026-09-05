#!/usr/bin/env bash
# Grid Keep-Awake — durable anti-sleep (Lyra: Mac 不得睡眠拖死定时任务)
# Uses caffeinate assertions (no sudo). Optionally applies pmset if passwordless sudo works.
set -euo pipefail
LOG_DIR="${HOME}/Library/Logs/demo-grid"
mkdir -p "$LOG_DIR"
LOG="${LOG_DIR}/keep-awake.log"
ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG" >/dev/null; }

# Best-effort pmset (root). sleep already 0 on this machine; pin displaysleep too when possible.
if command -v sudo >/dev/null 2>&1; then
  if sudo -n true 2>/dev/null; then
    sudo -n pmset -a sleep 0 disksleep 0 displaysleep 0 2>>"$LOG" || true
    sudo -n pmset -a disablesleep 1 2>>"$LOG" || true
    log "pmset applied via passwordless sudo"
  else
    log "WARN pmset needs one-time: sudo pmset -a sleep 0 disksleep 0 displaysleep 0"
  fi
fi

log "caffeinate -dims starting (prevent idle/display/disk/system sleep)"
# -d display  -i idle  -m disk  -s system (AC); on battery -s may be ignored — -dim still holds idle
exec /usr/bin/caffeinate -dims -t 0
