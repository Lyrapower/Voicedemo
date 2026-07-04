#!/bin/bash
# Grid Sovereign Runtime — one-command deploy
# Run from project root: bash deploy.sh

set -e

echo "=== Grid Sovereign Runtime Deploy ==="

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "FAIL: python3 not found"
    exit 1
fi
echo "PASS python3 found"

# 2. Install deps (minimal)
pip install fastapi uvicorn pydantic httpx --quiet 2>/dev/null || \
pip install fastapi uvicorn pydantic httpx --quiet --break-system-packages 2>/dev/null
echo "PASS dependencies installed"

# 3. Check Ollama
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "WARNING: Ollama not reachable at localhost:11434"
    echo "  Start Ollama first, or adjust configs/gateway_config.json"
else
    echo "PASS Ollama reachable"
    echo "  Models available:"
    curl -s http://localhost:11434/api/tags | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    print(f'    - {m[\"name\"]}')
" 2>/dev/null || echo "    (could not list models)"
fi

# 4. Init cleanroom
if [ ! -f ".grid_cleanroom/grid_hmac.key" ]; then
    python3 scripts/cleanroom.py init
    echo "PASS cleanroom initialized"
else
    echo "PASS cleanroom already initialized"
fi

# 5. Run selftest
python3 scripts/cleanroom.py selftest
echo "PASS cleanroom selftest"

# 6. Verify directory structure
echo ""
echo "=== Project Structure ==="
echo "gateway/local_gateway.py    — sovereign gateway (run this)"
echo "scripts/cleanroom.py        — trace signing + verification"
echo "policy/                     — cleanroom rules"
echo "configs/                    — local config (NOT prompts)"
echo "protection/                 — sealed declarations (DO NOT TOUCH)"
echo "traces/                     — signed trace output"
echo "feedback/                   — calibration feedback"
echo ".cursor/rules/              — Cursor behavioral boundary"

echo ""
echo "=== Ready ==="
echo "Start gateway:  python3 gateway/local_gateway.py"
echo "Health check:   curl http://127.0.0.1:8501/health"
echo ""
echo "No API keys. No cloud. Local only."
