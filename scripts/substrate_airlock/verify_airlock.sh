#!/usr/bin/env bash
# Run substrate airlock acceptance + optional live compile smoke.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== Unit acceptance (3 cases) ==="
python3 "$ROOT/scripts/substrate_airlock/run_acceptance.py"
echo ""

if curl -sf --max-time 2 http://127.0.0.1:8501/health >/dev/null 2>&1; then
  echo "=== Live /compile smoke (optional) ==="
  curl -s --max-time 180 -X POST http://127.0.0.1:8501/compile \
    -H 'Content-Type: application/json' \
    -d '{"signal":"能听到我吗"}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
p = d.get('proof') or {}
print('verdict:', d.get('verdict'))
print('proof:', json.dumps(p, ensure_ascii=False))
"
else
  echo "SKIP live compile — gateway :8501 not up"
fi
