#!/usr/bin/env bash
# due files: morning-final.md midday-final.md earnings-final.md — 缺 GLM 终稿则 repair_shift
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCOUT="${ROOT}/grid-scout"
LOG_DIR="${HOME}/Library/Logs/demo-grid"
mkdir -p "$LOG_DIR" "${SCOUT}/state"
LOG="${LOG_DIR}/scout-land-integrity.log"
FAIL_STAMP="${SCOUT}/state/land_FAIL"
LOCK="${SCOUT}/state/integrity.lock"
ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG" >/dev/null; }

export PATH="/usr/bin:/bin:/usr/sbin:/Library/Frameworks/Python.framework/Versions/3.13/bin:${PATH:-}"
if [[ -f "${SCOUT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCOUT}/.env"
  set +a
fi
export SCOUT_OUT="${SCOUT_OUT:-$SCOUT}"
export GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8501}"
export WORKBENCH_URL="${WORKBENCH_URL:-http://127.0.0.1:8515}"
export SCOUT_SKIP_ASTER="${SCOUT_SKIP_ASTER:-1}"
export SCOUT_REVIEW="${SCOUT_REVIEW:-expanded}"
export DS_MAX_TOKENS="${DS_MAX_TOKENS:-16000}"
export SCOUT_DS_ATTEMPTS="${SCOUT_DS_ATTEMPTS:-5}"
export DEEPSEEK_BASE="${DEEPSEEK_BASE:-http://127.0.0.1:11434/v1}"
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-ollama}"
export DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro:cloud}"

PY=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
if [[ ! -x "$PY" ]]; then PY=python3; fi
UID_NUM="$(id -u)"
AGENT_TIMEOUT="${SCOUT_AGENT_TIMEOUT:-900}"

run_timeout() {
  # macOS has no GNU timeout — use python
  local secs="$1"; shift
  "$PY" - "$secs" "$@" <<'PY'
import subprocess, sys
secs = int(sys.argv[1])
cmd = sys.argv[2:]
try:
    r = subprocess.run(cmd, timeout=secs)
    raise SystemExit(r.returncode)
except subprocess.TimeoutExpired:
    raise SystemExit(124)
PY
}

# Stale lock = previous integrity hung
if [[ -f "$LOCK" ]]; then
  age=$(( $(date +%s) - $(stat -f %m "$LOCK") ))
  if (( age > AGENT_TIMEOUT + 120 )); then
    log "STALE lock age=${age}s → remove and continue"
    rm -f "$LOCK"
  else
    log "SKIP integrity already running (lock age=${age}s)"
    exit 0
  fi
fi
echo $$ >"$LOCK"
trap 'rm -f "$LOCK"' EXIT

wait_url() {
  local url="$1" label="$2" n="${3:-12}"
  local i=1
  while (( i <= n )); do
    if curl -sf --max-time 5 "$url" >/dev/null 2>&1; then
      log "dep ok ${label}"
      return 0
    fi
    if (( i == 3 )); then
      case "$label" in
        ollama) launchctl kickstart -k "gui/${UID_NUM}/com.demo.grid.ollama11434" 2>/dev/null || true ;;
        gateway8501)
          launchctl kickstart -k "gui/${UID_NUM}/com.demo.grid.gateway8501" 2>/dev/null || true
          if [[ -x "${ROOT}/scripts/tailscale_serve_watchdog.sh" ]]; then
            bash "${ROOT}/scripts/tailscale_serve_watchdog.sh" >/dev/null 2>&1 || true
          fi
          ;;
      esac
      log "kickstart attempted for ${label}"
      sleep 5
    fi
    log "dep wait ${label} ${i}/${n}"
    sleep 5
    i=$((i + 1))
  done
  log "dep FAIL ${label}"
  return 1
}

stamp_fail() {
  printf '%s %s\n' "$(ts)" "$*" >"$FAIL_STAMP"
  log "FAIL_STAMP $*"
}

clear_fail() { rm -f "$FAIL_STAMP"; }

shift_landed() {
  local mode="$1"
  local jp="${SCOUT}/briefs/${DAY}-${mode}.json"
  local final="${SCOUT}/briefs/${DAY}-${mode}-final.md"
  local hp="${SCOUT}/briefs/${DAY}-${mode}.html"
  [[ -f "$jp" && -f "$final" && -f "$hp" ]] || return 1
  grep -q 'review_origin=glm52_cloud' "$final" || return 1
  grep -q 'review_origin=glm52_cloud' "$hp" || return 1
  grep -q 'GLM 编译终稿' "$hp" || return 1
  "$PY" - "$jp" <<'PY' || return 1
import json, sys
d = json.load(open(sys.argv[1]))
ds = d.get("ds") or {}
if ds.get("_parse_failed"):
    raise SystemExit(1)
cands = [c for c in (ds.get("candidates") or []) if isinstance(c, dict) and not c.get("empty")]
assert len(cands) >= 1, "no candidates"
print("ok", sys.argv[1], "cands", len(cands))
PY
}

ensure_deps() {
  wait_url "http://127.0.0.1:11434/api/tags" ollama 12 || stamp_fail "ollama down day=${DAY}"
  if ! curl -sf --max-time 5 http://127.0.0.1:11434/api/tags \
    | "$PY" -c 'import json,sys; ns=[m.get("name") for m in json.load(sys.stdin).get("models",[])];
raise SystemExit(0 if any("deepseek-v4-pro" in (n or "") for n in ns) else 1)'; then
    log "REPAIR ollama pull deepseek-v4-pro:cloud"
    ollama pull deepseek-v4-pro:cloud >>"$LOG" 2>&1 || stamp_fail "cannot pull deepseek-v4-pro:cloud"
  fi
  wait_url "${GATEWAY_URL}/health" gateway8501 12 || stamp_fail "gateway8501 down day=${DAY}"
}

repair_shift() {
  local mode="$1"
  log "REPAIR mode=${mode} → scout_agent + land"
  ensure_deps
  set +e
  run_timeout "$AGENT_TIMEOUT" "$PY" "${SCOUT}/scout_agent.py" --mode "$mode" >>"$LOG" 2>&1
  rc_agent=$?
  set -e
  if [[ "$rc_agent" -eq 124 ]]; then
    stamp_fail "scout_agent TIMEOUT ${AGENT_TIMEOUT}s mode=${mode} day=${DAY}"
    exit 1
  fi
  if [[ "$rc_agent" -ne 0 ]]; then
    log "FAIL scout_agent exit=${rc_agent} mode=${mode}"
    stamp_fail "scout_agent exit=${rc_agent} mode=${mode} day=${DAY}"
  fi
  set +e
  run_timeout 480 "$PY" "${ROOT}/scripts/scout_land_option.py" --date "$DAY" --mode "$mode" >>"$LOG" 2>&1
  rc_land=$?
  set -e
  if [[ "$rc_land" -ne 0 ]]; then
    log "FAIL scout_land_option exit=${rc_land} mode=${mode}"
    stamp_fail "scout_land_option exit=${rc_land} mode=${mode} day=${DAY}"
  fi
  if ! shift_landed "$mode"; then
    stamp_fail "${mode} not GLM-landed (final+html glm52_cloud) day=${DAY}"
    exit 1
  fi
  log "AFTER mode=${mode} glm_final=yes"
}

cd "$SCOUT"
DAY="$(python3 - <<'PY'
import fetchers
print(fetchers.trading_date().isoformat())
PY
)"
HOUR="$(date +%H)"
MIN="$(date +%M)"
NOW_MIN=$((10#$HOUR * 60 + 10#$MIN))
log "check day=${DAY} now=${HOUR}:${MIN}"

# Due by local clock (plist 无时区 = 本机). 班次起跑后留 15min 给 DS,再强制 land.
# morning 06:45 → 06:50; midday 10:40 → 10:55; earnings 12:35/12:45 → 12:50
DUE=""
if (( NOW_MIN >= 6 * 60 + 50 )); then DUE="${DUE} morning"; fi
if (( NOW_MIN >= 10 * 60 + 55 )); then DUE="${DUE} midday"; fi
if (( NOW_MIN >= 12 * 60 + 50 )); then DUE="${DUE} earnings"; fi

for mode in $DUE; do
  jp="${SCOUT}/briefs/${DAY}-${mode}.json"
  final="${SCOUT}/briefs/${DAY}-${mode}-final.md"
  hp="${SCOUT}/briefs/${DAY}-${mode}.html"
  log "check mode=${mode} json=$([[ -f $jp ]] && echo yes || echo NO) html=$([[ -f $hp ]] && echo yes || echo NO) final=$([[ -f $final ]] && echo yes || echo NO)"
  if shift_landed "$mode"; then
    log "OK ${mode} GLM 终稿在"
  else
    repair_shift "$mode"
  fi
done

RP="${SCOUT}/briefs/${DAY}-review.json"
EF="${SCOUT}/briefs/${DAY}-evening-final.md"
if [[ "$HOUR" -ge 21 ]]; then
  if [[ ! -f "$EF" ]] || ! grep -q 'review_origin=glm52_cloud' "$EF"; then
    stamp_fail "evening-final missing glm52_cloud day=${DAY}"
    exit 1
  fi
  log "OK evening-final glm52_cloud for ${DAY}"
fi
if [[ -f "${SCOUT}/briefs/${DAY}-morning.json" && ! -f "$RP" ]]; then
  if [[ "$HOUR" -ge 21 || "${SCOUT_FORCE_REVIEW:-0}" == "1" ]]; then
    log "REPAIR review.json missing for ${DAY} → build_review"
    if ! "$PY" - <<PY >>"$LOG" 2>&1
import os, sys
sys.path.insert(0, "${SCOUT}")
os.chdir("${SCOUT}")
import scout_agent
rev = scout_agent.build_review("${DAY}")
if not rev:
    raise SystemExit("build_review returned None")
print("review ok", rev.get("hit"), "legs", len(rev.get("legs") or []))
PY
    then
      stamp_fail "build_review failed day=${DAY}"
      exit 1
    fi
    log "AFTER review=yes"
  else
    log "NOTE review.json absent (ok before 21:00; evening/integrity 21:20 will fill)"
  fi
elif [[ -f "$RP" ]]; then
  log "OK review.json present for ${DAY}"
fi

# Emit: 已到期班次各自要有 aether_scout_brief(mode=…)
EMIT2="$("$PY" - "$DAY" "$DUE" "${GATEWAY_URL}" <<'PY'
import json, sys, urllib.request
day, due, gw = sys.argv[1], sys.argv[2].split(), sys.argv[3]
need = [m for m in due if m.strip()]
if not need:
    print(1)
    raise SystemExit
try:
    with urllib.request.urlopen(gw + "/store/events/recent?source=aether&kinds=aether_scout_brief&per_kind=12", timeout=8) as r:
        d = json.loads(r.read().decode())
except Exception:
    print(0)
    raise SystemExit
arr = d if isinstance(d, list) else d.get("events") or d.get("items") or []
have = set()
for e in arr:
    p = e.get("payload") or e
    if str(p.get("date") or "")[:10] != day:
        continue
    m = str(p.get("mode") or "").strip()
    if m:
        have.add(m)
missing = [m for m in need if m not in have]
print(0 if missing else 1)
if missing:
    sys.stderr.write("emit missing %s\n" % ",".join(missing))
PY
)"
if [[ "$EMIT2" != "1" ]]; then
  stamp_fail "OPTION emit still missing for due shifts day=${DAY} due=${DUE}"
  exit 1
fi

clear_fail
log "PASS day=${DAY} due=${DUE}"
exit 0
