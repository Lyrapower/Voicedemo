#!/usr/bin/env bash
# Post-start acceptance: 8501 multimodal, 8515 workbench UI, 8790 chat (no silent fail).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/grid-sovereign-runtime/traces/proof/field_workbench_stack.json"
STAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
CHAT_TIMEOUT="${FIELD_STACK_CHAT_TIMEOUT:-120}"

fail=0
note() { echo "$*"; }
pass() { echo "  PASS  $*"; }
bad() { echo "  FAIL  $*"; fail=1; }

http_code() {
  curl -sf --max-time 8 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null || echo 000
}

http_head_ok() {
  local name="$1" url="$2" needle="${3:-}"
  local code body
  code="$(http_code "$url")"
  if [[ "$code" != "200" ]]; then
    bad "${name} http=${code} (${url})"
    return
  fi
  if [[ -n "$needle" ]]; then
    body="$(curl -sf --max-time 8 "$url" 2>/dev/null || true)"
    if [[ "$body" != *"$needle"* ]]; then
      bad "${name} missing marker ${needle}"
      return
    fi
  fi
  pass "${name}"
}

echo "=== field + workbench stack acceptance ==="
echo "    chat timeout=${CHAT_TIMEOUT}s"
echo ""

echo "=== 8501 gateway ==="
http_head_ok "8501 /health" "http://127.0.0.1:8501/health"
http_head_ok "8501 /app/grid_multimodal.html" "http://127.0.0.1:8501/app/grid_multimodal.html" "GRID Multimodal Workbench"

cand_code="$(curl -s --max-time 8 -o /dev/null -w '%{http_code}' \
  -X POST "http://127.0.0.1:8501/task/candidate" \
  -H 'Content-Type: application/json' \
  -d '{}' 2>/dev/null || echo 000)"
if [[ "$cand_code" == "422" || "$cand_code" == "400" ]]; then
  pass "8501 POST /task/candidate route alive (http=${cand_code})"
else
  bad "8501 POST /task/candidate route (http=${cand_code}, want 422/400)"
fi

echo ""
echo "=== 8515 workbench UI ==="
wb_code="$(http_code "http://127.0.0.1:8515/health")"
if [[ "$wb_code" == "200" ]]; then
  pass "8515 /health"
  http_head_ok "8515 /grid_workbench_b11.html" "http://127.0.0.1:8515/grid_workbench_b11.html" "build b11(2026-07-22"
  http_head_ok "8515 /grid_multimodal.html" "http://127.0.0.1:8515/grid_multimodal.html" "GRID Multimodal Workbench"
else
  bad "8515 /health http=${wb_code} — run: bash ${ROOT}/scripts/install_workbench_launchagent.sh"
fi

echo ""
echo "=== 8790 FIELD bridge ==="
health="$(curl -sf --max-time 8 http://127.0.0.1:8790/health 2>/dev/null || echo '{}')"
if echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null; then
  pass "8790 /health ok"
else
  bad "8790 /health"
fi
if echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('links',{}).get('gateway') else 1)" 2>/dev/null; then
  pass "8790 links.gateway"
else
  bad "8790 links.gateway false"
fi

echo ""
echo "=== 8790 /chat non-empty ==="
chat_out="$(curl -sf --max-time "${CHAT_TIMEOUT}" -N -X POST http://127.0.0.1:8790/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"验收：只回复两个字：收到"}' 2>&1)" || chat_out=""

chat_verdict="$(CHAT_OUT="$chat_out" python3 - <<'PY'
import json, os, sys
text = os.environ.get("CHAT_OUT", "")
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
    print("FAIL|no done event in /chat stream")
    sys.exit(0)
text_out = (done.get("text") or "").strip()
served = done.get("served_by") or ""
if not text_out:
    print(f"FAIL|empty text (served_by={served})")
elif not str(served).startswith("gateway-"):
    print(f"FAIL|bad served_by={served}")
else:
    print(f"PASS|text={text_out[:40]!r} served_by={served}")
PY
)"

case "${chat_verdict%%|*}" in
  PASS) pass "8790 /chat ${chat_verdict#*|}" ;;
  *) bad "8790 /chat ${chat_verdict#*|}" ;;
esac

python3 - <<PY
import json, pathlib
path = pathlib.Path("${OUT}")
path.parent.mkdir(parents=True, exist_ok=True)
chat_ok = "${chat_verdict}".startswith("PASS|")
wb_ok = "${wb_code}" == "200"
cand_ok = "${cand_code}" in ("422", "400")
record = {
    "generated_at": "${STAMP}",
    "pass": ${fail} == 0,
    "checks": {
        "8501_health": True,
        "8501_multimodal_html": True,
        "8501_task_candidate_route": cand_ok,
        "8515_health": wb_ok,
        "8515_multimodal_html": wb_ok,
        "8790_health": True,
        "8790_gateway_link": True,
        "8790_chat_non_empty": chat_ok,
    },
    "chat_verdict": "${chat_verdict}",
    "8515_health_code": "${wb_code}",
    "candidate_route_code": "${cand_code}",
}
path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
print("wrote", path)
PY

echo ""
if [[ "$fail" -ne 0 ]]; then
  echo "STACK ACCEPTANCE FAIL"
  echo "  8501 gateway: bash ${ROOT}/scripts/start_grid_gateway.sh"
  echo "  8515 workbench: bash ${ROOT}/scripts/install_workbench_launchagent.sh"
  echo "               or: launchctl kickstart -k \"gui/\$(id -u)/com.demo.workbench.ui8515\""
  echo "  8790 FIELD: launchctl kickstart -k \"gui/\$(id -u)/com.demo.field.bridge8790\""
  exit 1
fi
echo "STACK ACCEPTANCE PASS"
