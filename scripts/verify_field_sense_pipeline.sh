#!/usr/bin/env bash
# FIELD_SENSE_PIPELINE acceptance (steps 1–3 smoke)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0
ok(){ echo "PASS: $*"; PASS=$((PASS+1)); }
bad(){ echo "FAIL: $*"; FAIL=$((FAIL+1)); }

echo "=== Step 1: Garden telemetry (8787) ==="
if curl -sf -m 2 http://127.0.0.1:8787/health >/dev/null 2>&1; then
  T=$(curl -sf -m 2 http://127.0.0.1:8787/telemetry.json || true)
  if echo "$T" | python3 -c "import sys,json; j=json.load(sys.stdin); assert 'ts' in j; print('ts',j.get('ts'))"; then
    ok "8787 /telemetry.json has ts"
  else
    bad "8787 /telemetry.json missing ts"
  fi
  if curl -sf -m 2 http://127.0.0.1:8787/api/anchor/sketch >/dev/null; then
    ok "8787 /api/anchor/sketch"
  else
    bad "8787 /api/anchor/sketch"
  fi
else
  echo "SKIP: 8787 not running"
fi

echo "=== Step 2: field_now v1.6 (8795) ==="
/usr/bin/python3 "$ROOT/tests/test_field_now_v16.py" && ok "field_now v1.6 unit tests"
if curl -sf -m 2 http://127.0.0.1:8795/now.json >/dev/null 2>&1; then
  J=$(curl -sf -m 2 http://127.0.0.1:8795/now.json)
  if echo "$J" | python3 -c "import sys,json; j=json.load(sys.stdin); assert 'garden' in j; print(j.get('garden'))"; then
    ok "8795 /now.json flat garden fields"
  else
    bad "8795 /now.json missing garden"
  fi
else
  echo "SKIP: 8795 not running (start: scripts/start_field_now_8795.sh)"
fi

echo "=== Step 3: b11 field sense markers ==="
B11="$ROOT/grid-sovereign-runtime/workbench/static/grid_workbench_b11.html"
rg -q 'senseField|fieldLine|fieldLight|cField' "$B11" && ok "b11 field sense JS present"
rg -q '场感知已附' "$B11" && ok "b11 field meta line"
if rg -q 'fieldLine.*candidateCall|candidateCall.*fieldLine' "$B11"; then
  bad "field sense leaked into candidate path"
else
  ok "field sense not wired to candidate"
fi

echo "=== Summary: $PASS passed, $FAIL failed ==="
[[ "$FAIL" -eq 0 ]]
