#!/usr/bin/env bash
# P0 Grid chain integrity — static CI gate (no live 8501 required).
# Fails closed: any forbidden routing/fallback/FINAL pattern → exit 1 (block release).
# 不用依赖 brew rg:系统 PATH 可能无 ripgrep。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-}"
fail=0
ok(){ echo "  PASS  $*"; }
bad(){ echo "  FAIL  $*"; fail=1; }

# grep -E portable helpers (no ripgrep required)
_has(){ grep -Eq "$1" "$2"; }
_has_not_in_homechat_api(){
  # homeChat 函数体前 80 行不得出现 /api/chat
  awk '/async function homeChat/{f=1} f{print; if(++n>=80) exit}' "$1" | grep -Eq '/api/chat' && return 1
  return 0
}
_defaultgw_has_origin(){
  awk '/function defaultGw\(\)/{f=1} f{print; if(/^}/) exit}' "$1" | grep -Eq 'location\.origin'
}

echo "=== Grid chain integrity (P0 static gate) ==="

B11="${ROOT}/grid-sovereign-runtime/workbench/static/grid_workbench_b11.html"
GRID="${ROOT}/grid-sovereign-runtime/gateway/static/grid.html"

for f in "$B11" "$GRID"; do
  [[ -f "$f" ]] && ok "found $(basename "$f")" || { bad "missing $f"; continue; }
done

cd "$ROOT"
python3 -m unittest grid-sovereign-runtime.tests.test_grid_chain_integrity_static -q \
  && ok "test_grid_chain_integrity_static.py" \
  || bad "test_grid_chain_integrity_static.py"

python3 -m unittest grid-sovereign-runtime.tests.test_infrastructure_guard -q \
  && ok "test_infrastructure_guard.py" \
  || bad "test_infrastructure_guard.py"

python3 "${ROOT}/scripts/grid_infrastructure_guard.py" verify-runtime \
  && ok "infrastructure lock verify-runtime" \
  || bad "infrastructure lock verify-runtime"

python3 "${ROOT}/grid-sovereign-runtime/workbench/test_b11_gateway_default.py" -q \
  && ok "test_b11_gateway_default.py" \
  || bad "test_b11_gateway_default.py"

# Forbidden: silent Ollama fallback in b11 homeChat
if _has_not_in_homechat_api "$B11"; then
  ok "b11 homeChat no /api/chat"
else
  bad "b11 homeChat still references /api/chat (silent fallback risk)"
fi

# Forbidden: defaultGw uses location.origin on workbench (8515 trap)
if _defaultgw_has_origin "$B11"; then
  bad "b11 defaultGw still uses location.origin"
else
  ok "b11 defaultGw no location.origin"
fi

# Required: gateway lock helpers
_has 'function gatewayApiOrigin' "$B11" && ok "b11 gatewayApiOrigin" || bad "b11 gatewayApiOrigin missing"
_has 'function rejectInvalidGateway' "$B11" && ok "b11 rejectInvalidGateway" || bad "b11 rejectInvalidGateway missing"

# Forbidden: expanded/home failure catch 渲染 finalCard(成功卡)
# HOME 已迁 EXPANDED;send() catch 必须用 card err
if awk '/async function send\(\)/{f=1} f{print; if(/^}/ && ++c==1) exit}' "$B11" \
    | grep -E 'catch\(e\)' -A6 | grep -Eq 'finalCard\('; then
  bad "b11 send catch may still render finalCard on failure"
else
  ok "b11 send failure path avoids finalCard"
fi

# grid.html: ts.net must force defaultGw
if grep -Eq 'endsWith\("\.ts\.net"\)' "$GRID" && grep -Eq 'function resolveGw' "$GRID"; then
  ok "grid resolveGw ts.net lock"
else
  bad "grid resolveGw missing ts.net → defaultGw"
fi

# Rule file must exist (release guard documented)
RULE="${ROOT}/.cursor/rules/grid-chain-integrity-redzone.mdc"
[[ -f "$RULE" ]] && ok "redzone rule present" || bad "missing grid-chain-integrity-redzone.mdc"
IMM="${ROOT}/.cursor/rules/grid-infrastructure-immutable.mdc"
[[ -f "$IMM" ]] && ok "immutable rule present" || bad "missing grid-infrastructure-immutable.mdc"
LOCK="${ROOT}/config/grid_infrastructure_lock.json"
[[ -f "$LOCK" ]] && ok "infrastructure lock manifest" || bad "missing grid_infrastructure_lock.json"

if [[ "$fail" -ne 0 ]]; then
  echo ""
  echo "=== P0 CHAIN INTEGRITY FAILED — release blocked ==="
  exit 1
fi
echo ""
echo "=== P0 static gate ALL PASS ==="
