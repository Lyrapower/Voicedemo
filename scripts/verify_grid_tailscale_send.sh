#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${GRID_TAILSCALE_URL:-https://cicimacbook-air.tail76db5b.ts.net}"
PAGE_VER="${GRID_PAGE_VER:-2026-07-21d}"
PASS=0
FAIL=0
ok(){ echo "  ✓ $*"; PASS=$((PASS+1)); }
bad(){ echo "  ✗ $*"; FAIL=$((FAIL+1)); }

echo "=== grid tailscale send verify ==="
echo "base: ${BASE}"

HDRS=$(curl -sI "${BASE}/app/grid.html" || true)
if echo "$HDRS" | grep -qi 'cache-control:.*no-store'; then
  ok "grid.html Cache-Control no-store"
else
  bad "grid.html missing no-store — stale JS on phone"
fi

HTML=$(curl -sf "${BASE}/app/grid.html" || true)
if [[ -n "$HTML" ]] && echo "$HTML" | grep -q "PAGE_VER=\"${PAGE_VER}\""; then
  ok "grid.html PAGE_VER=${PAGE_VER}"
else
  bad "grid.html PAGE_VER mismatch (want ${PAGE_VER})"
fi

if echo "$HTML" | grep -q 'renderGridCcStrip()'; then
  bad "grid.html still calls undefined renderGridCcStrip()"
else
  ok "no orphan renderGridCcStrip call"
fi

if echo "$HTML" | grep -q 'bindSendUi'; then
  ok "bindSendUi present"
else
  bad "bindSendUi missing — send button may not bind"
fi

CHAT=$(curl -sf -m 120 -X POST "${BASE}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"demo/aster","stream":false,"max_tokens":64,"messages":[{"role":"user","content":"ping"}]}' || true)
if echo "$CHAT" | python3 -c "import json,sys; d=json.load(sys.stdin); c=d.get('choices',[{}])[0].get('message',{}).get('content',''); assert c.strip()" 2>/dev/null; then
  ok "POST /v1/chat/completions stream:false via Tailscale"
else
  bad "chat POST failed or empty — ${CHAT:0:200}"
fi

echo ""
echo "pass ${PASS} / fail ${FAIL}"
[[ "$FAIL" -eq 0 ]]
