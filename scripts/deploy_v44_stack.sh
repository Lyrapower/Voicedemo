#!/usr/bin/env bash
# v4.4 deploy: grid-sovereign-runtime + aster anchor v0.2 + clear 9B prompts
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
export PYTHONPATH="${ROOT}:${ROOT}/repo${PYTHONPATH:+:${PYTHONPATH}}"

echo "=== Aster anchor v0.2 ==="
test -f "$ROOT/config/aster_anchor.toml" || { echo "FAIL: config/aster_anchor.toml missing"; exit 1; }
python3 -c "
import tomllib
from pathlib import Path
p = Path('$ROOT/config/aster_anchor.toml')
# anchor pack uses # comments — parse meta.version manually
text = p.read_text(encoding='utf-8')
ver = 'unknown'
for line in text.splitlines():
    if line.strip().startswith('version ='):
        ver = line.split('=',1)[1].strip().strip('\"')
        break
print(f'anchor pack v{ver} @ {p.resolve()}')
"

echo "=== LM Studio: clear 9B system prompts ==="
ASTER_DEPLOY_CLEAR=1 "$ROOT/scripts/deploy_lmstudio_aster.sh"

echo "=== Grid Sovereign Runtime v4.4 ==="
cd "$ROOT/grid-sovereign-runtime"
bash deploy.sh

echo "=== Restart gateway :8501 ==="
for pid in $(lsof -t -iTCP:8501 -sTCP:LISTEN 2>/dev/null || true); do kill "$pid" 2>/dev/null; done
sleep 1
nohup python3 gateway/local_gateway.py > /tmp/grid_gateway.log 2>&1 &
sleep 2

echo "=== Verify ==="
curl -sf http://127.0.0.1:8501/health | python3 -m json.tool
echo "--- /gateway (no contract) ---"
curl -sf -X POST http://127.0.0.1:8501/gateway \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"hello in one short line","user_id":"deploy"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print('routed_to', d.get('routed_to'), 'len', len(d.get('response') or ''))"
echo "--- endpoints ---"
curl -sf http://127.0.0.1:8501/openapi.json | python3 -c "import sys,json; p=[x for x in json.load(sys.stdin)['paths'] if 'compile' in x or x=='/gateway']; print('\n'.join(sorted(p)))"

echo "=== DONE v4.4 ==="
