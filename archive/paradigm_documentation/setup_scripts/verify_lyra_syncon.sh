#!/usr/bin/env bash
# Prove LYRA + SynCon are present on disk and in LM Studio tabs (A/B separate).
set -euo pipefail
ENI="$(cd "$(dirname "$0")/.." && pwd)"
FAIL=0

check_file() {
  local f="$1" label="$2"
  if grep -q "LYRA ANCHOR" "$f" && grep -q "SynCon" "$f"; then
    echo "OK  $label"
  else
    echo "FAIL $label (missing LYRA/SynCon)"
    FAIL=1
  fi
}

check_file "$ENI/prompts/echo_nodes_system.txt" "Entry A prompt file"
check_file "$ENI/prompts/entry_b_compile_system.txt" "Entry B prompt file"
if grep -q '"name": "LYRA"' "$ENI/incoming/echo_nodes/syncon/config/anchor.json" \
  && grep -q 'SynCon Lab' "$ENI/incoming/echo_nodes/syncon/config/anchor.json"; then
  echo "OK  SynCon anchor.json"
else
  echo "FAIL SynCon anchor.json"
  FAIL=1
fi

python3 <<PY
import json
from pathlib import Path
home = Path.home() / ".lmstudio/conversations"
for cid, name in [("17797865158101", "A Echo"), ("17797865158102", "B Compile")]:
    p = home / f"{cid}.conversation.json"
    sp = json.loads(p.read_text(encoding="utf-8")).get("systemPrompt", "")
    ok = "LYRA ANCHOR" in sp and "SynCon" in sp
    print(f"{'OK' if ok else 'FAIL'}  LM Studio tab {name} ({cid}) len={len(sp)}")
    if not ok:
        raise SystemExit(1)
PY

if curl -sf --max-time 3 "http://127.0.0.1:8500/health" >/dev/null 2>&1; then
  curl -sf "http://127.0.0.1:8500/health" | python3 -c "
import sys,json
d=json.load(sys.stdin)
a=d.get('anchor',{})
print('OK  A :8500 health lyra=', a.get('frequency_authority'), 'prompt_has_lyra=', a.get('lm_studio_prompt_has_lyra'))
"
else
  echo "WARN A :8500 not running (start with scripts/start_entry_a_8500.sh)"
fi

exit $FAIL
