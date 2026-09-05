#!/usr/bin/env bash
# Acceptance: FIELD chat truncation fix — handoff_protocol JSON + continuation metadata.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/grid-sovereign-runtime/traces/proof/field_truncation_fix.json"
PROMPT='handoff_protocol: output valid JSON only with keys status, round_id, owner, input_block, audit_block, compile_pack, decision_block, execution_result, proof_link. No markdown.'

echo "=== health task_budgets ==="
curl -sf http://127.0.0.1:8790/health | python3 -m json.tool | head -20

echo ""
echo "=== handoff_protocol /chat ==="
chat_out="$(curl -sf --max-time 300 -N -X POST http://127.0.0.1:8790/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"handoff_protocol: output valid JSON only with keys status, round_id, owner, input_block, audit_block, compile_pack, decision_block, execution_result, proof_link. No markdown.","task_type":"handoff_protocol"}' 2>&1)" || chat_out=""

python3 - <<'PY' "$chat_out" "$OUT"
import json, pathlib, sys
text = sys.argv[1]
out_path = pathlib.Path(sys.argv[2])
done = None
for line in text.splitlines():
    if not line.startswith("data:"):
        continue
    try:
        d = json.loads(line[5:].strip())
    except Exception:
        continue
    if d.get("done"):
        done = d
        break
if not done:
    print("FAIL: no done event"); sys.exit(1)
ok = (
    done.get("task_type") == "handoff_protocol"
    and done.get("max_tokens") == 4096
    and done.get("finish_reason") in ("stop", "length")
    and (
        done.get("finish_reason") == "stop"
        or done.get("merged_json_valid") is True
        or done.get("status") == "INCOMPLETE_ARTIFACT"
    )
)
if done.get("merged_json_valid"):
    assert done.get("status") == "PASS"
elif done.get("truncated"):
  assert done.get("status") == "INCOMPLETE_ARTIFACT" or not done.get("artifact", {}).get("ok")
record = {
    "done": {k: done[k] for k in done if k != "text"},
    "text_len": len(done.get("text") or ""),
    "pass": ok,
}
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(record, ensure_ascii=False, indent=2))
sys.exit(0 if ok else 1)
PY
