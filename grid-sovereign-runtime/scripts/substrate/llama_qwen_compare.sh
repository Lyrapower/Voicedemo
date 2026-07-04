#!/usr/bin/env bash
# Side-by-side substrate compare: LM Studio :1234 vs llama.cpp :1235.
# Does NOT touch gateway config or LM Studio settings.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROOF_DIR="$ROOT/traces/proof"
REPORT="$PROOF_DIR/llama_vs_lmstudio_compare.json"
LM_BASE="${LM_BASE:-http://127.0.0.1:1234/v1}"
LLAMA_BASE="${LLAMA_BASE:-http://127.0.0.1:1235/v1}"
MODEL="${MODEL:-qwen/qwen3.5-9b}"
ACCEPT="$ROOT/scripts/substrate/llama_qwen_acceptance.sh"

mkdir -p "$PROOF_DIR"

run_probe() {
  local label="$1" base="$2"
  echo
  echo "========== $label ($base) =========="
  BASE="$base" MODEL="$MODEL" bash "$ACCEPT" || true
}

echo "=== Substrate compare (no gateway switch) ==="
echo "LM Studio:  $LM_BASE  (production, unchanged)"
echo "llama.cpp:  $LLAMA_BASE  (shadow compare port)"
echo

if ! curl -sf "$LM_BASE/models" >/dev/null 2>&1; then
  echo "FAIL: LM Studio not reachable at $LM_BASE — keep local server running" >&2
  exit 1
fi

if ! curl -sf "$LLAMA_BASE/models" >/dev/null 2>&1; then
  echo "FAIL: llama.cpp not reachable at $LLAMA_BASE" >&2
  echo "Start shadow server:" >&2
  echo "  PORT=1235 COMPARE_MODE=1 bash $ROOT/scripts/substrate/llama_qwen_server.sh" >&2
  exit 1
fi

LM_LOG="$(mktemp)"
LLAMA_LOG="$(mktemp)"
trap 'rm -f "$LM_LOG" "$LLAMA_LOG"' EXIT

BASE="$LM_BASE" MODEL="$MODEL" bash "$ACCEPT" | tee "$LM_LOG" || true
BASE="$LLAMA_BASE" MODEL="$MODEL" bash "$ACCEPT" | tee "$LLAMA_LOG" || true

python3 - <<'PY' "$REPORT" "$LM_LOG" "$LLAMA_LOG" "$LM_BASE" "$LLAMA_BASE"
import json, re, sys
from datetime import datetime, timezone

report_path, lm_log, llama_log, lm_base, llama_base = sys.argv[1:6]

def parse(path):
    text = open(path).read()
    fails = len(re.findall(r"^FAIL:", text, re.M))
    passes = len(re.findall(r"^PASS:", text, re.M))
    overall = "PASS" if "=== OVERALL: PASS ===" in text else "FAIL"
    reasoning = bool(re.search(r"reasoning_content field present", text))
    return {"overall": overall, "pass_count": passes, "fail_count": fails, "reasoning_leak": reasoning}

lm = parse(lm_log)
ll = parse(llama_log)
winner = "llama.cpp" if ll["overall"] == "PASS" and lm["overall"] != "PASS" else (
    "lm_studio" if lm["overall"] == "PASS" and ll["overall"] != "PASS" else (
        "tie" if lm["overall"] == ll["overall"] == "PASS" else "neither"
    )
)
switch_ready = ll["overall"] == "PASS" and not ll["reasoning_leak"]

doc = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "mode": "compare_no_switch",
    "lm_studio": {"base": lm_base, **lm},
    "llama_cpp": {"base": llama_base, **ll},
    "winner": winner,
    "switch_ready": switch_ready,
    "note": "switch_ready=true only when llama compare port passes all probes with no reasoning leak; gateway unchanged until manual cutover",
}
open(report_path, "w").write(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc, indent=2))
print(f"\nReport: {report_path}")
if switch_ready:
    print("VERDICT: llama.cpp compare PASS — eligible for cutover (see docs/LM_STUDIO_TO_LLAMA_CPP.md § switch)")
    sys.exit(0)
print("VERDICT: NOT ready to switch — fix llama compare failures first")
sys.exit(1)
PY
