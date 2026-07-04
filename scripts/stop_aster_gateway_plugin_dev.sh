#!/usr/bin/env bash
set -euo pipefail
PID_FILE="${TMPDIR:-/tmp}/aster-grid-gateway-lms-dev.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo "OK: no dev server pid file"
  exit 0
fi
pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid" 2>/dev/null || true
  echo "OK: stopped lms dev (pid $pid)"
else
  echo "OK: pid $pid not running"
fi
rm -f "$PID_FILE"
