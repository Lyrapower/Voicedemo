#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
set -a
# shellcheck source=/dev/null
[ -f session.env ] && . session.env
set +a

PORT=8500
for pid in $(lsof -t -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true); do
  echo "Stopping stale listener on :${PORT} (pid ${pid})"
  kill "${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
done
sleep 0.5

echo "Starting Entry A Echo gateway on 127.0.0.1:${PORT}..."
exec python3 -m uvicorn echo_nodes_fastapi:app --host 127.0.0.1 --port "${PORT}"
