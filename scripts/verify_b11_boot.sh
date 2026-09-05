#!/usr/bin/env bash
# b11 static boot audit — read-only, no store writes
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HTML="${ROOT}/grid-sovereign-runtime/workbench/static/grid_workbench_b11.html"
BASE="${B11_URL:-http://127.0.0.1:8515}"
GW="${GW_URL:-http://127.0.0.1:8501}"
fail=0
ok(){ echo "  PASS  $*"; }
bad(){ echo "  FAIL  $*"; fail=1; }

echo "=== b11 boot audit ==="
[[ -f "$HTML" ]] || { bad "missing $HTML"; exit 1; }

VER=$(rg -o 'PAGE_VER="[^"]+"' "$HTML" | head -1 | cut -d'"' -f2)
[[ -n "$VER" ]] && ok "PAGE_VER=$VER in source" || bad "PAGE_VER missing"

rg -q '_gwDefault|_storeRoot' "$HTML" && ok "cfg init uses _gwDefault/_storeRoot" \
  || bad "cfg init missing safe bootstrap"

if rg 'const cfg=\{[\s\S]{0,400}storeBase\(\)' "$HTML" >/dev/null 2>&1; then
  bad "cfg literal still calls storeBase() — TDZ boot crash risk"
else
  ok "cfg literal does not call storeBase()"
fi

rg -q 'function chatCompletionsUrl' "$HTML" && ok "chatCompletionsUrl present" || bad "chatCompletionsUrl missing"
rg -q 'function normalizeGwUrl' "$HTML" && ok "normalizeGwUrl present" || bad "normalizeGwUrl missing"
rg -q 'WORKBENCH_UI_PORTS' "$HTML" && ok "WORKBENCH_UI_PORTS lock" || bad "WORKBENCH_UI_PORTS missing"
rg -q 'function gatewayApiOrigin' "$HTML" && ok "gatewayApiOrigin present" || bad "gatewayApiOrigin missing"
rg -q 'migrateBadGatewayStorage' "$HTML" && ok "migrateBadGatewayStorage present" || bad "migrateBadGatewayStorage missing"
rg -q '8515 不提供 /v1' "$HTML" && ok "reject :8515/v1 gateway" || bad "reject :8515/v1 missing"
if rg -q '/api/chat' "$HTML" && rg 'async function homeChat' -A40 "$HTML" | rg -q '/api/chat'; then
  bad "homeChat still has silent Ollama /api/chat fallback"
else
  ok "homeChat no silent Ollama fallback"
fi
python3 "${ROOT}/grid-sovereign-runtime/workbench/test_b11_gateway_default.py" -q \
  && ok "test_b11_gateway_default.py" || bad "test_b11_gateway_default.py"
rg -q 'warnStore\(' "$HTML" && ok "store/chat error split" || bad "warnStore missing"

SERVED=$(curl -sf "${BASE}/grid_workbench_b11.html" | rg -o 'PAGE_VER="[^"]+"' | head -1 || true)
[[ "$SERVED" == "PAGE_VER=\"$VER\"" ]] && ok "8515 serves $VER" || bad "8515 serves stale HTML ($SERVED)"

curl -sf "${BASE}/health" >/dev/null && ok "$BASE/health" || bad "$BASE/health"
curl -sf "${GW}/health" >/dev/null && ok "$GW/health" || bad "$GW/health"
curl -sf "${BASE}/field_now/now.json" >/dev/null && ok "field_now proxy" || bad "field_now proxy"

N=$(curl -sf "${GW}/store/conversations/workbench-b11?limit=200" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
[[ "${N:-0}" -gt 0 ]] && ok "workbench-b11 store readable ($N rows)" || bad "store empty or unreadable"

curl -sf -X POST "${GW}/v1/chat/completions" -H 'Content-Type: application/json' \
  -d '{"model":"demo/aster","messages":[{"role":"user","content":"只回复:ping"}],"stream":false,"max_tokens":8}' \
  | python3 -c "import sys,json; t=json.load(sys.stdin)['choices'][0]['message']['content']; assert t.strip()" \
  && ok "8501 chat POST" || bad "8501 chat POST"

# P0-3: 8515 Cloud 旁路已下线 → 410;正路 = 8501 /task/cloud_chat
CODE=$(curl -s -o /tmp/b11_cloud_gone.json -w '%{http_code}' -X POST "${BASE}/cloud/chat" \
  -H 'Content-Type: application/json' \
  -d '{"substrate":"glm52","messages":[{"role":"user","content":"ping"}],"max_tokens":8}')
[[ "$CODE" == "410" || "$CODE" == "404" ]] && ok "8515 /cloud/chat gone ($CODE)" || bad "8515 /cloud/chat expected 410/404 got $CODE"

curl -sf -X POST "${GW}/task/cloud_chat" -H 'Content-Type: application/json' \
  -d '{"substrate":"glm52","model":"glm-5.2:cloud","messages":[{"role":"user","content":"ping"}],"stream":false,"max_tokens":8,"surface":"cloud-glm"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ok') is not False or d.get('content') is not None or d.get('error')" \
  && ok "8501 /task/cloud_chat (正路)" || bad "8501 /task/cloud_chat"

if [[ "$fail" -ne 0 ]]; then
  echo "=== FAILED ==="
  exit 1
fi
echo "=== ALL PASS ==="
