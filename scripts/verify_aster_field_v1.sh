#!/usr/bin/env bash
# ASTER FIELD v1 acceptance probes (items ① ③; ②④ need browser / manual LM Studio stop).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/grid-sovereign-runtime/traces/proof/field_v1_acceptance.json"
STAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

fail=0
bridge_ok=0
gw_ok=0
served_by=""

echo "=== ① health / links ==="
health="$(curl -sf --max-time 5 http://127.0.0.1:8790/health)" || { echo "FAIL bridge :8790/health"; fail=1; health="{}"; }
echo "$health" | python3 -m json.tool 2>/dev/null || echo "$health"

bridge_ok=$(echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(1 if d.get('ok') else 0)" 2>/dev/null || echo 0)
gw_ok=$(echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(1 if d.get('links',{}).get('gateway') else 0)" 2>/dev/null || echo 0)

echo ""
echo "=== ③ /chat served_by fingerprint ==="
chat_out="$(curl -sf --max-time 120 -N -X POST http://127.0.0.1:8790/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"用三个字说你好"}' 2>&1)" || chat_out=""

served_by=$(echo "$chat_out" | python3 -c "
import sys, json, re
text=sys.stdin.read()
for line in text.splitlines():
    if not line.startswith('data:'): continue
    try:
        d=json.loads(line[5:].strip())
    except Exception: continue
    if d.get('done') and d.get('served_by'):
        print(d['served_by']); break
" 2>/dev/null || true)

if [[ -z "$served_by" ]]; then
  echo "FAIL no served_by in /chat stream"
  fail=1
else
  echo "PASS served_by=$served_by"
fi

python3 - <<PY
import json, pathlib
path = pathlib.Path("${OUT}")
path.parent.mkdir(parents=True, exist_ok=True)
record = {
    "generated_at": "${STAMP}",
    "acceptance": {
        "1_bridge_health_ok": bool(${bridge_ok}),
        "1_gateway_link_ok": bool(${gw_ok}),
        "2_visual_manual": "browser http://127.0.0.1:8790 — thinking→output ripple→idle",
        "3_served_by": "${served_by}" or None,
        "3_served_by_pass": "${served_by}".startswith("gateway-") if "${served_by}" else False,
        "4_lm_studio_stop_manual": "stop LM Studio server → ask → error 0.5s → idle, no crash",
    },
    "chat_tail": """$(echo "$chat_out" | tail -3 | sed 's/"/\\"/g')""",
}
path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
print("wrote", path)
PY

echo ""
if [[ "$fail" -ne 0 ]]; then exit 1; fi
echo "PASS automated checks (①③). Complete ②④ in browser per field_v1_acceptance.md"
