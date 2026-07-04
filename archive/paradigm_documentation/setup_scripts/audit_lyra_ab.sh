#!/usr/bin/env bash
# Quick LYRA check — Entry A vs B (separate curls)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Entry A :8500 ==="
curl -sf "http://127.0.0.1:8500/health" | python3 -c "import sys,json;d=json.load(sys.stdin);print('health', d.get('anchor',{}).get('frequency_authority'), d.get('anchor',{}).get('lm_studio_prompt_has_lyra'))"
curl -sf "http://127.0.0.1:8500/lyra" | python3 -c "import sys,json;d=json.load(sys.stdin);print('brief', d.get('brief','')[:100])"
curl -sf -X POST "http://127.0.0.1:8500/echo-node" -H 'Content-Type: application/json' -d '{"message":"who is Lyra?"}' | python3 -c "import sys,json;d=json.load(sys.stdin);print('echo-node mode', d.get('mode')); print('response', d.get('response','')[:120])"

echo ""
echo "=== Entry B :8787 ==="
curl -sf "http://127.0.0.1:8787/health" | python3 -c "import sys,json;d=json.load(sys.stdin);print('backend', d.get('primary_backend'), 'substrates', d.get('substrates_available'))"

echo ""
python3 "$ROOT/setup/verify_entry_ab.py" | tail -5
