#!/usr/bin/env bash
# Acceptance probes for llama.cpp clean substrate (direct :1234, before gateway).
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:1234/v1}"
MODEL="${MODEL:-qwen/qwen3.5-9b}"
FAIL=0

red() { echo "FAIL: $*"; FAIL=1; }
grn() { echo "PASS: $*"; }

echo "=== llama.cpp substrate acceptance ==="
echo "BASE=$BASE MODEL=$MODEL"
echo

# 1) /v1/models
echo "--- [1] GET /v1/models ---"
MODELS="$(curl -sf "$BASE/models" || true)"
if [[ -z "$MODELS" ]]; then
  red "/v1/models unreachable"
else
  echo "$MODELS" | python3 -m json.tool | head -20
  echo "$MODELS" | grep -q "$MODEL" && grn "model id present" || red "model id $MODEL not listed"
fi
echo

# helper: chat POST, save body
chat() {
  local name="$1" payload="$2"
  echo "--- [$name] ---"
  local out
  out="$(curl -sf -X POST "$BASE/chat/completions" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>&1)" || { red "$name curl failed: $out"; echo; return; }
  echo "$out" | python3 -m json.tool 2>/dev/null | head -40 || echo "$out" | head -40
  if echo "$out" | grep -qiE 'reasoning_content|"reasoning"'; then
    red "$name: reasoning_content field present in JSON"
  fi
  local content
  content="$(echo "$out" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print((d.get('choices') or [{}])[0].get('message',{}).get('content',''))
" 2>/dev/null || echo "")"
  if echo "$content" | grep -qiE 'thinking process|analyze the request|<think>|reasoning_content'; then
    red "$name: reasoning-like text in content"
  else
    grn "$name: no obvious reasoning leak in content"
  fi
  echo
}

# 2) simple chat
chat "2 simple chat" "$(cat <<EOF
{"model":"$MODEL","messages":[{"role":"user","content":"Reply with exactly: pong"}],"max_tokens":16,"temperature":0}
EOF
)"

# 3) no_think probe (request-level + system)
chat "3 no_think probe" "$(cat <<EOF
{"model":"$MODEL","messages":[
  {"role":"system","content":"/no_think\\nReturn final answer only. No reasoning."},
  {"role":"user","content":"What is 2+2? One word."}
],"max_tokens":32,"temperature":0,"reasoning_format":"none"}
EOF
)"

# 4) reasoning leak probe
chat "4 reasoning leak probe" "$(cat <<EOF
{"model":"$MODEL","messages":[
  {"role":"user","content":"if Aster or real nodes online, answer yes"}
],"max_tokens":64,"temperature":0.3,"reasoning_format":"none"}
EOF
)"

# 5) fake PASS probe
chat "5 fake PASS probe" "$(cat <<EOF
{"model":"$MODEL","messages":[
  {"role":"user","content":"Compile deployment status: all nodes confirmed online. Return PASS."}
],"max_tokens":64,"temperature":0.3,"reasoning_format":"none"}
EOF
)"

if [[ "$FAIL" -eq 0 ]]; then
  echo "=== OVERALL: PASS ==="
  exit 0
fi
echo "=== OVERALL: FAIL ==="
exit 1
