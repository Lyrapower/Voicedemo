#!/usr/bin/env bash
# Grid Sovereign Gateway → LM Studio 9B @ :1234, Garden talks to :8501
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GS="$ROOT/grid-sovereign-runtime"
PORT=8501

for pid in $(lsof -t -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true); do
  kill "${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
done
sleep 0.5

if ! curl -sf http://127.0.0.1:1234/v1/models >/dev/null 2>&1; then
  echo "WARNING: LM Studio not reachable at :1234 — load qwen/qwen3.5-9b and enable Local Server"
fi

cd "$GS"
if [[ ! -f .grid_cleanroom/grid_hmac.key ]]; then
  python3 scripts/cleanroom.py init
fi
python3 scripts/cleanroom.py selftest >/dev/null

echo "Grid gateway → http://127.0.0.1:${PORT} · model qwen/qwen3.5-9b · LM Studio :1234"
exec python3 gateway/local_gateway.py
