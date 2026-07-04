#!/usr/bin/env bash
# Rollback llama.cpp substrate → LM Studio backend for gateway :1234.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GW_CFG="$ROOT/configs/gateway_config.json"
PLIST="${PLIST:-$HOME/Library/LaunchAgents/com.grid.llama-qwen-server.plist}"

echo "=== Rollback: llama.cpp → LM Studio ==="

# 1) Stop launchd llama server
if [[ -f "$PLIST" ]]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || \
    launchctl unload "$PLIST" 2>/dev/null || true
  echo "Stopped launchd: com.grid.llama-qwen-server"
fi
pkill -f "llama-server.*Qwen3.5-9B" 2>/dev/null || true

# 2) Restore gateway endpoint (compile / Aster / Jarvis logic untouched)
python3 - <<'PY' "$GW_CFG"
import json, sys
path = sys.argv[1]
cfg = json.loads(open(path).read())
cfg["openai_endpoint"] = "http://localhost:1234/v1"
# openai_model stays qwen/qwen3.5-9b — LM Studio identifier may differ; adjust in UI if needed
open(path, "w").write(json.dumps(cfg, indent=2) + "\n")
print(f"Restored {path}: openai_endpoint -> http://localhost:1234/v1")
PY

# 3) Restart gateway to pick up config (if running)
if pgrep -f "gateway/local_gateway.py" >/dev/null; then
  pkill -f "gateway/local_gateway.py" || true
  sleep 1
  cd "$ROOT"
  nohup python3 gateway/local_gateway.py > /tmp/grid_gateway.log 2>&1 &
  echo "Gateway restarted (compile logic unchanged)"
fi

echo
echo "Next: start LM Studio → Developer → Local Server on port 1234"
echo "Verify: curl -s http://127.0.0.1:8501/health"
echo "Compile route unchanged — still POST :8501/compile"
