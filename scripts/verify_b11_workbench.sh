#!/usr/bin/env bash
# b11 workbench acceptance — agent runs this; user is not QA.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
B11="$ROOT/grid-sovereign-runtime/workbench/static/grid_workbench_b11.html"
FAIL=0

say() { printf '%s\n' "$*"; }
ok() { say "  OK  $*"; }
bad() { say "  FAIL $*"; FAIL=1; }

say "=== b11 workbench verify ==="

# 1) JS must parse (catches broken fetchJsonWithTimeout / orphaned braces)
python3 - "$B11" <<'PY' || FAIL=1
import re, sys
from pathlib import Path
src = Path(sys.argv[1]).read_text(encoding="utf-8")
m = re.search(r"<script>([\s\S]*)</script>\s*\n\s*</body>", src)
if not m:
    print("  FAIL no <script> block"); sys.exit(1)
js = m.group(1)
# brace balance (strings/comments stripped roughly)
stack = 0
for i, ch in enumerate(js):
    if ch == "{": stack += 1
    elif ch == "}":
        stack -= 1
        if stack < 0:
            print(f"  FAIL extra }} at char {i}"); sys.exit(1)
if stack != 0:
    print(f"  FAIL unbalanced braces stack={stack}"); sys.exit(1)
# regression: 403 block must exist intact
if "if(r.status===403){" not in js:
    print("  FAIL missing if(r.status===403)"); sys.exit(1)
if 'id="b11-shell"' not in src:
    print("  FAIL missing b11-shell critical script"); sys.exit(1)
print("  OK  JS brace balance + 403 handler + shell")
PY

# 2) Services
curl -sf http://127.0.0.1:8501/health >/dev/null && ok "8501 health" || bad "8501 health"
curl -sf http://127.0.0.1:8515/health >/dev/null && ok "8515 health" || bad "8515 health"

# 3) Store intact (never purged by agent)
STORE_N=$(curl -sf 'http://127.0.0.1:8501/store/conversations/workbench-b11' | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
if [[ "${STORE_N}" -ge 1 ]]; then ok "workbench-b11 store ${STORE_N} msgs"; else bad "workbench-b11 store empty"; fi

# 4) PAGE_VER served
PV=$(curl -sf http://127.0.0.1:8515/grid_workbench_b11.html | rg -o 'PAGE_VER="[^"]+"' | head -1)
[[ -n "$PV" ]] && ok "served $PV" || bad "PAGE_VER missing"

# 5) Gateway proxy chat (no browser; no store write)
HTTP=$(curl -s -o /tmp/b11_verify_chat.json -w '%{http_code}' -X POST http://127.0.0.1:8515/gateway/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"demo/aster","messages":[{"role":"user","content":"只回复:验"}],"stream":false,"max_tokens":2048}')
if [[ "$HTTP" == "200" ]]; then
  python3 -c "import json; j=json.load(open('/tmp/b11_verify_chat.json')); m=j.get('grid_meta') or {}; assert m.get('max_tokens_sent')==2048, m; print('  OK  proxy chat 200 max_tokens_sent=2048')"
else
  bad "proxy chat HTTP $HTTP"
fi

# 5b) Leading assistant must not 502 (Qwen jinja user-query regression)
HTTP2=$(curl -s -o /tmp/b11_verify_asst_user.json -w '%{http_code}' -X POST http://127.0.0.1:8515/gateway/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"demo/aster","messages":[{"role":"assistant","content":"prior fail card"},{"role":"user","content":"只回复:好"}],"stream":false,"max_tokens":8}')
if [[ "$HTTP2" == "200" ]]; then
  ok "leading-assistant normalize 200"
else
  bad "leading-assistant normalize HTTP $HTTP2"
fi

# 6) Cloud memory on 8501 store (cloud-glm52) — read-only verify
N8501=$(curl -sf 'http://127.0.0.1:8501/store/conversations/cloud-glm52?limit=500' | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
if [[ "${N8501}" -ge 1 ]]; then ok "8501 cloud-glm52 store ${N8501} msgs"; else bad "8501 cloud-glm52 empty"; fi
if rg -q 'fetchCloudStoreAll|cloudChatUrl|cloud8501Base|/task/cloud_chat' "$B11" \
  && ! rg -q 'cloudMemoryUrl\(|location\.origin.*/cloud/chat' "$B11"; then
  ok "b11 Cloud: 8501 store + /task/cloud_chat"
else
  bad "b11 Cloud wiring broken"
fi

# 7) Python unit tests
if python3 "$ROOT/grid-sovereign-runtime/gateway/test_token_budget.py" -q 2>/dev/null; then
  ok "test_token_budget.py (client max_tokens ceiling)"
else
  bad "test_token_budget.py"
fi

if python3 "$ROOT/grid-sovereign-runtime/workbench/test_b11_gateway_default.py" -q 2>/dev/null; then
  ok "test_b11_gateway_default.py"
else
  bad "test_b11_gateway_default.py"
fi

if python3 "$ROOT/grid-sovereign-runtime/workbench/test_cloud_store.py" -q 2>/dev/null; then
  ok "test_cloud_store.py"
else
  bad "test_cloud_store.py"
fi

if python3 -m unittest "$ROOT/tests/test_cloud_chat_executor.py" -q 2>/dev/null; then
  ok "test_cloud_chat_executor.py (empty_content policy locked)"
else
  bad "test_cloud_chat_executor.py"
fi

CODE=$(curl -s -o /tmp/b11_cloud_gone2.json -w '%{http_code}' -X POST 'http://127.0.0.1:8515/cloud/chat' \
  -H 'Content-Type: application/json' \
  -d '{"substrate":"glm52","messages":[{"role":"user","content":"ping"}],"max_tokens":8}')
[[ "$CODE" == "410" || "$CODE" == "404" ]] && ok "8515 /cloud/chat gone ($CODE)" || bad "8515 /cloud/chat expected 410/404 got $CODE"

if [[ "$FAIL" -ne 0 ]]; then
  say "=== FAILED ==="
  exit 1
fi
say "=== PASSED ==="
