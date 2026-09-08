#!/usr/bin/env bash
# Grid Sovereign Gateway → LM Studio 9B @ :1234, Garden talks to :8501
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GS="$ROOT/grid-sovereign-runtime"
PORT=8501

for pid in $(lsof -t -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true); do
  kill "${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
done
sleep 1.5

if ! curl -sf http://127.0.0.1:1234/v1/models >/dev/null 2>&1; then
  echo "WARNING: LM Studio not reachable at :1234 — load qwen/qwen3.5-9b and enable Local Server"
fi

if python3 -c "import json; from pathlib import Path; cfg=json.loads(Path('$GS/configs/gateway_config.json').read_text()); raise SystemExit(0 if not cfg.get('coder_routing_enabled') else 1)" 2>/dev/null; then
  :
else
  if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "WARNING: coder_routing_enabled but Ollama :11434 down — run scripts/install_ollama_coder.sh"
  fi
fi

cd "$GS"
set +x
# GRID_STORE_TOKEN is optional. Do not load it from config/grid_store.token.
# File presence must not enable store auth; unset inherited env from prior runs.
unset GRID_STORE_TOKEN || true
if [[ -f "$GS/config/bridge_store.token" ]]; then
  export BRIDGE_STORE_TOKEN="$(tr -d '\n' < "$GS/config/bridge_store.token")"
fi
if [[ ! -f .grid_cleanroom/grid_hmac.key ]]; then
  python3 scripts/cleanroom.py init
fi
python3 scripts/cleanroom.py selftest >/dev/null

python3 "$ROOT/scripts/grid_infrastructure_guard.py" verify-runtime

echo "Grid gateway → http://127.0.0.1:${PORT} · chat LM Studio :1234 · compile/task Ollama coder :11434"
exec python3 gateway/gateway_serve.py
