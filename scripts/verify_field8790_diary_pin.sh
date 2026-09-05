#!/usr/bin/env bash
# 8790 日记：pin_set 时无 token 必 401；dist 不得含「有 token 就跳过 PIN」逻辑。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PANEL="${ROOT}/aster-field/frontend/src/diary/panel.ts"
DIST="${ROOT}/aster-field/frontend/dist/assets"
BASE="${FIELD8790_URL:-http://127.0.0.1:8790}"

fail=0
pass() { echo "PASS  $*"; }
bad()  { echo "FAIL  $*"; fail=1; }

echo "=== backend: pin_set + GET /diary without token ==="
settings="$(curl -sf --max-time 5 "${BASE}/diary/settings" 2>/dev/null || echo '{}')"
pin_set="$(echo "$settings" | python3 -c "import sys,json; print(json.load(sys.stdin).get('pin_set', False))" 2>/dev/null || echo False)"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${BASE}/diary" 2>/dev/null || echo 000)"
if [[ "$pin_set" == "True" && "$code" == "401" ]]; then
  pass "GET /diary -> 401 when pin_set"
elif [[ "$pin_set" != "True" ]]; then
  pass "pin not set (skip 401 check)"
else
  bad "GET /diary expected 401, got ${code}"
fi

echo "=== source: open() pin gate ==="
if python3 - <<'PY' "$PANEL"
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
if "if (cfg.pin_set && !authToken)" in src:
    print("bypass")
    raise SystemExit(1)
if not re.search(r"async function open\(\).*?if \(cfg\.pin_set\) \{\s*clearDiaryToken\(\);", src, re.S):
    print("no_clear")
    raise SystemExit(2)
print("ok")
PY
then
  pass "open() always clearDiaryToken when pin_set (no token bypass)"
else
  ec=$?
  [[ "$ec" == 1 ]] && bad "panel.ts still skips PIN when sessionStorage has token"
  [[ "$ec" == 2 ]] && bad "open() missing clearDiaryToken on pin_set"
fi

echo "=== dist: reply bar + no token bypass ==="
js="$(ls -t "${DIST}"/index-*.js 2>/dev/null | head -1 || true)"
if [[ -z "$js" ]]; then
  bad "no dist bundle — run: cd aster-field/frontend && npm run build"
elif rg -q '写给它的回信|diary-reply-bar' "$js"; then
  pass "dist includes diary reply UI"
else
  bad "dist missing diary-reply-bar"
fi
if [[ -n "$js" ]] && rg -q 'pin_set&&!|pin_set && !' "$js" 2>/dev/null; then
  bad "dist may skip PIN when token present"
else
  pass "dist has no obvious token-skip PIN pattern"
fi

html="$(curl -sf --max-time 5 "${BASE}/" 2>/dev/null || true)"
if printf '%s' "$html" | rg -q 'index-.*\.js'; then
  pass "8790 serves built index"
else
  bad "8790 index not reachable"
fi

echo "=== unit: test_diary_pin_gate ==="
(cd "${ROOT}/aster-field" && python3 -m unittest tests.test_diary_pin_gate -q) || bad "unittest test_diary_pin_gate"

exit "$fail"
