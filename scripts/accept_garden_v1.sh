#!/usr/bin/env bash
# Garden v1 acceptance — hits 8790 only; does not probe or restart 8787/8788.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${GARDEN_V1_PORT:-8790}"
BASE="http://127.0.0.1:${PORT}"
REPORT="${ROOT}/deliver/proof/garden_v1/ACCEPTANCE_REPORT.md"
NOW_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

mkdir -p "${ROOT}/deliver/proof/garden_v1" "${ROOT}/logs"

pass=true
checks=()

check() {
  local name="$1"
  local ok="$2"
  if [[ "$ok" == "true" ]]; then
    checks+=("- PASS - ${name}")
  else
    checks+=("- FAIL - ${name}")
    pass=false
  fi
}

health_code="$(curl -s -o /tmp/garden_v1_health.json -w "%{http_code}" "${BASE}/health" 2>/dev/null || echo 000)"
check "GET ${BASE}/health → 200" "$([[ "$health_code" == "200" ]] && echo true || echo false)"

backend_ok=false
if [[ "$health_code" == "200" ]]; then
  if python3 - <<'PY' 2>/dev/null
import json, pathlib
d = json.loads(pathlib.Path("/tmp/garden_v1_health.json").read_text())
raise SystemExit(0 if d.get("backend") == "macos_tts" else 1)
PY
  then
    backend_ok=true
  fi
fi
check "health backend=macos_tts" "$backend_ok"

tel_code="$(curl -s -o /tmp/garden_v1_tel.json -w "%{http_code}" "${BASE}/api/telemetry" 2>/dev/null || echo 000)"
check "GET ${BASE}/api/telemetry → 200" "$([[ "$tel_code" == "200" ]] && echo true || echo false)"

voice_code="$(curl -s -o /tmp/garden_v1_voice.json -w "%{http_code}" -X POST "${BASE}/api/voice" \
  -H "Content-Type: application/json" \
  -d '{"voiceFreq":440,"voiceAmp":0.5}' 2>/dev/null || echo 000)"
check "POST ${BASE}/api/voice → 200" "$([[ "$voice_code" == "200" ]] && echo true || echo false)"

speak_code="$(curl -s -o /tmp/garden_v1_speak.json -w "%{http_code}" -X POST "${BASE}/api/speak" \
  -H "Content-Type: application/json" \
  -d '{"text":"Garden v1 acceptance ping."}' 2>/dev/null || echo 000)"
check "POST ${BASE}/api/speak → 200" "$([[ "$speak_code" == "200" ]] && echo true || echo false)"

speak_status=""
if [[ "$speak_code" == "200" ]]; then
  speak_status="$(python3 - <<'PY' 2>/dev/null || true
import json, pathlib
print(json.loads(pathlib.Path("/tmp/garden_v1_speak.json").read_text()).get("status", ""))
PY
)"
fi
check "speak status queued or busy" "$([[ "$speak_status" == "queued" || "$speak_status" == "busy" ]] && echo true || echo false)"

ui_ok=false
if grep -q '127.0.0.1:8790' "${ROOT}/scripts/sound_lab_fallback.py" 2>/dev/null; then
  ui_ok=true
fi
check "5173 UI points API to 8790" "$ui_ok"

{
  echo "# Garden v1 Acceptance Report"
  echo
  echo "Generated: ${NOW_UTC}"
  echo
  echo "## Scope"
  echo "- Garden v1 API on port ${PORT} (macOS TTS)"
  echo "- 8787 / 8788 intentionally not modified by this script"
  echo
  echo "## Checks"
  for c in "${checks[@]}"; do
    echo "$c"
  done
  echo
  if [[ "$pass" == "true" ]]; then
    echo "VERDICT: PASS"
    echo "[$NOW_UTC] ACCEPTANCE_PASS | scope=garden_v1" >> "${ROOT}/logs/audit.log"
  else
    echo "VERDICT: FAIL"
    echo "[$NOW_UTC] ACCEPTANCE_FAIL | scope=garden_v1" >> "${ROOT}/logs/audit.log"
  fi
} > "$REPORT"

if [[ "$pass" == "true" ]]; then
  echo "Garden v1 PASS — report: ${REPORT}"
  exit 0
fi
echo "Garden v1 FAIL — report: ${REPORT}"
exit 1
