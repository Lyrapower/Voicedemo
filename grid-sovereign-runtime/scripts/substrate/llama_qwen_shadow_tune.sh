#!/usr/bin/env bash
# Shadow-only: try limited llama-server flag variants on :1235, run shadow eval.
# Does NOT touch LM Studio (:1234) or gateway (:8501).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="/tmp/grid-llama-qwen"
PORT=1235
EVAL="$ROOT/scripts/qwen_substrate_eval_shadow.py"
SERVER="$ROOT/scripts/substrate/llama_qwen_server.sh"
REPORT="$ROOT/traces/proof/shadow_tune_results.json"

mkdir -p "$LOG_DIR" "$ROOT/traces/proof"

if [[ -z "${LLAMA_SERVER:-}" ]]; then
  LLAMA_SERVER="${LLAMA_SERVER:-$HOME/opt/llama.cpp/build/bin/llama-server}"
fi

stop_shadow() {
  pkill -f "llama-server.*--port $PORT" 2>/dev/null || true
  pkill -f "llama-server.*127.0.0.1:$PORT" 2>/dev/null || true
  sleep 2
}

start_shadow() {
  local extra_flags="$1"
  local tag="$2"
  stop_shadow
  echo "=== start shadow variant: $tag ==="
  echo "flags: $extra_flags"
  PORT=$PORT COMPARE_MODE=1 LLAMA_SERVER="$LLAMA_SERVER" \
    SHADOW_EXTRA_FLAGS="$extra_flags" SHADOW_TEMP=0 SHADOW_TOP_P=0.8 \
    bash "$SERVER" > "$LOG_DIR/shadow-$tag.log" 2>&1 &
  local i
  for i in $(seq 1 90); do
    if curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
      echo "ready: $tag"
      return 0
    fi
    sleep 2
  done
  echo "FAIL: shadow server did not become ready ($tag)" >&2
  tail -30 "$LOG_DIR/shadow-$tag.log" >&2 || true
  return 1
}

run_eval() {
  local tag="$1"
  local out
  if out="$(python3 "$EVAL" 2>&1)"; then
    echo "$out"
    echo "{\"variant\":\"$tag\",\"overall\":\"PASS\"}"
    return 0
  fi
  echo "$out"
  echo "{\"variant\":\"$tag\",\"overall\":\"FAIL\"}"
  return 1
}

declare -a VARIANTS=(
  "A|--reasoning off --jinja --reasoning-format none"
  "B|--reasoning off --jinja --reasoning-format deepseek"
  "C|--reasoning off --no-jinja --reasoning-format none"
)

results="["
first=1
best=""
best_ok=0

for entry in "${VARIANTS[@]}"; do
  tag="${entry%%|*}"
  flags="${entry#*|}"
  if ! start_shadow "$flags" "$tag"; then
    row="{\"variant\":\"$tag\",\"overall\":\"FAIL\",\"reason\":\"server_start_failed\"}"
  else
    set +e
    eval_out="$(run_eval "$tag")"
    rc=$?
    set -e
    overall="$(echo "$eval_out" | tail -1 | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["overall"])' 2>/dev/null || echo FAIL)"
    row="{\"variant\":\"$tag\",\"flags\":\"$flags\",\"overall\":\"$overall\"}"
    if [[ "$overall" == "PASS" && "$best_ok" -eq 0 ]]; then
      best="$tag"
      best_ok=1
    fi
  fi
  if [[ "$first" -eq 1 ]]; then first=0; else results+=","; fi
  results+="$row"
done

results+="]"
printf '%s\n' "$results" | python3 -m json.tool > "$REPORT"

echo
echo "=== shadow tune complete ==="
cat "$REPORT"
if [[ "$best_ok" -eq 1 ]]; then
  echo "BEST: variant $best — eligible for compare re-run"
  exit 0
fi

echo "ALL VARIANTS FAIL — see $REPORT and failure notes below"
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("grid-sovereign-runtime/traces/proof/qwen_substrate_eval_shadow.json")
if not p.exists():
    p = pathlib.Path("/Users/ciciwang/Desktop/demo/grid-sovereign-runtime/traces/proof/qwen_substrate_eval_shadow.json")
if p.exists():
    r = json.loads(p.read_text())
    for c in r.get("cases", []):
        if c.get("status") != "PASS":
            print(f"- FAIL {c['probe']}/{c['case_id']}: {c['routes'][0].get('text_preview','')[:120]}")
PY
echo
echo "Next candidates:"
echo "  1) Qwen3.5-9B-Q5_K_M (same repo, better instruction follow)"
echo "  2) llama.cpp server + --chat-template-kwargs '{\"enable_thinking\":false}'"
echo "  3) vLLM / MLX-LM with explicit thinking disabled"
echo "  4) 14B only after 9B shadow PASS"
exit 1
