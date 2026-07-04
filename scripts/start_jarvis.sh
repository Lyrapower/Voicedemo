#!/usr/bin/env bash
# Sole Jarvis entry — localhost only; no public port exposure.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${JARVIS_PORT:-8686}"
HOST="${JARVIS_HOST:-127.0.0.1}"
echo "Jarvis sole entry: app.platform_main:app → http://${HOST}:${PORT}"
echo "Tasks registry: GET http://${HOST}:${PORT}/api/jarvis/tasks"
exec python3 -m uvicorn app.platform_main:app --host "${HOST}" --port "${PORT}"
