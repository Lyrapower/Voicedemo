#!/usr/bin/env bash
# Keep demo/aster-grid-gateway visible in LM Studio → Generators.
# Installed plugins do not auto-register generators; lms dev must stay running.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_DIR="$ROOT/lmstudio-plugins/aster-grid-gateway"
PID_FILE="${TMPDIR:-/tmp}/aster-grid-gateway-lms-dev.pid"
LOG_FILE="${TMPDIR:-/tmp}/aster-grid-gateway-lms-dev.log"

if [[ ! -f "$PLUGIN_DIR/manifest.json" ]]; then
  echo "FAIL: missing $PLUGIN_DIR/manifest.json"
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "OK: lms dev already running (pid $old_pid)"
    echo "    log: $LOG_FILE"
    exit 0
  fi
fi

if ! command -v lms >/dev/null 2>&1; then
  echo "FAIL: lms CLI not found (open LM Studio once to install CLI)"
  exit 1
fi

if [[ ! -f "$HOME/.lmstudio/extensions/plugins/demo/aster-grid-gateway/manifest.json" ]]; then
  echo "Installing plugin first..."
  bash "$ROOT/scripts/install_aster_gateway_plugin.sh"
fi

cd "$PLUGIN_DIR"
nohup lms dev --no-notify >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
sleep 3

if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "FAIL: lms dev exited — see $LOG_FILE"
  tail -20 "$LOG_FILE" 2>/dev/null || true
  exit 1
fi

if rg -q "Registering generator" "$LOG_FILE" 2>/dev/null || \
   rg -q "setGenerator" "$HOME/.lmstudio/server-logs"/*/2026-*.log 2>/dev/null | tail -1 | rg -q "demo/aster-grid-gateway"; then
  echo "OK: demo/aster-grid-gateway dev server running (pid $(cat "$PID_FILE"))"
else
  echo "WARN: dev server started but generator registration not confirmed yet"
  echo "      check $LOG_FILE and LM Studio → Generators"
fi
echo "LM Studio: Aster tab → model picker → Generators → demo/aster-grid-gateway"
