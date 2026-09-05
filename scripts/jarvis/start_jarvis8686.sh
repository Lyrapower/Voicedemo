#!/usr/bin/env bash
# Jarvis workbench (:8686) — launchd entry only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PORT="${JARVIS_PORT:-8686}"
HOST="${JARVIS_HOST:-127.0.0.1}"

if lsof -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  pid="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -1)"
  if [[ -n "${pid}" ]] && ps -p "${pid}" -o command= 2>/dev/null | grep -q "platform_main"; then
    exit 0
  fi
fi

exec python3 -m uvicorn app.platform_main:app --host "${HOST}" --port "${PORT}"
