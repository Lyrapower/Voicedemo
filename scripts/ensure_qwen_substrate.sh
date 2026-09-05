#!/usr/bin/env bash
# Ensure LM Studio server + single qwen/qwen3.5-9b resident (no idle TTL unload).
set -euo pipefail
export PATH="${HOME}/.lmstudio/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
LOG_DIR="${HOME}/Library/Logs/demo-grid"
mkdir -p "$LOG_DIR" /tmp/demo-grid
LOG="${LOG_DIR}/qwen-substrate-watchdog.log"
MODEL="${QWEN_MODEL_ID:-qwen/qwen3.5-9b}"
LMS="${HOME}/.lmstudio/bin/lms"
ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG" >/dev/null; }

# Substrate only — never park virtual demo/aster here (empty LMS content → reload storm → diary Timeout).
case "$MODEL" in
  demo/aster|aster|*/aster)
    log "REFUSE QWEN_MODEL_ID=${MODEL} — must be physical qwen substrate (qwen/qwen3.5-9b)"
    exit 1
    ;;
esac

# Serialize — concurrent ensure caused dual load (qwen + qwen:2) and chat timeouts.
# macOS has no flock(1); use mkdir lock.
LOCKDIR="/tmp/demo-grid/qwen-substrate.lockdir"
mkdir -p /tmp/demo-grid
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  # stale?
  if [[ -f "$LOCKDIR/pid" ]]; then
    old="$(cat "$LOCKDIR/pid" 2>/dev/null || true)"
    if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
      log "SKIP another ensure running pid=$old"
      exit 0
    fi
    rm -rf "$LOCKDIR"
    mkdir "$LOCKDIR" || { log "SKIP lock busy"; exit 0; }
  else
    rm -rf "$LOCKDIR"
    mkdir "$LOCKDIR" || { log "SKIP lock busy"; exit 0; }
  fi
fi
echo $$ >"$LOCKDIR/pid"
trap 'rm -rf "$LOCKDIR"' EXIT

if [[ ! -x "$LMS" ]]; then
  log "FAIL lms missing at $LMS"
  exit 1
fi

if ! pgrep -f 'LM Studio.app/Contents/MacOS/LM Studio' >/dev/null 2>&1; then
  log "LM Studio app not running → open"
  open -a "LM Studio" || true
  sleep 8
fi

if ! curl -sf --max-time 5 http://127.0.0.1:1234/v1/models >/dev/null 2>&1; then
  log "server OFF → lms server start"
  "$LMS" server start --port 1234 >>"$LOG" 2>&1 || true
  sleep 3
fi
if ! curl -sf --max-time 5 http://127.0.0.1:1234/v1/models >/dev/null 2>&1; then
  log "FAIL :1234 still unreachable"
  exit 1
fi

PS="$("$LMS" ps 2>/dev/null || true)"
# Count rows for this model family
N="$(echo "$PS" | awk -v m="$MODEL" 'NR>1 && index($0,m){c++} END{print c+0}')"
TTL_BOUND=0
if echo "$PS" | grep -F "$MODEL" | grep -Eq '[0-9]+m[[:space:]]*/[[:space:]]*[0-9]+h|[0-9]+s[[:space:]]*/'; then
  TTL_BOUND=1
fi

need_reload=0
if [[ "$N" -lt 1 ]]; then need_reload=1; fi
if [[ "$TTL_BOUND" -eq 1 ]]; then need_reload=1; fi
if [[ "$N" -gt 1 ]]; then need_reload=1; fi  # collapse duplicates

if [[ "$need_reload" -eq 1 ]]; then
  log "reload need N=${N} ttl_bound=${TTL_BOUND}"
  "$LMS" unload --all >>"$LOG" 2>&1 || true
  # omit --ttl ⇒ no auto-unload
  if ! "$LMS" load "$MODEL" -y -c 8192 --parallel 4 >>"$LOG" 2>&1; then
    log "FAIL lms load ${MODEL}"
    exit 1
  fi
  sleep 2
fi

CODE="$(curl -sS -m 120 -o /tmp/qwen_keepalive.json -w '%{http_code}' \
  -X POST http://127.0.0.1:1234/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"reply exactly: ok\"}],\"max_tokens\":4,\"stream\":false,\"temperature\":0}" \
  || true)"
CONTENT="$(python3 - <<'PY'
import json
try:
  d=json.load(open("/tmp/qwen_keepalive.json"))
  print(((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
except Exception:
  print("")
PY
)"
if [[ "$CODE" != "200" || -z "${CONTENT// }" ]]; then
  log "FAIL chat probe http=${CODE} content='${CONTENT}' — one more reload"
  "$LMS" unload --all >>"$LOG" 2>&1 || true
  "$LMS" load "$MODEL" -y -c 8192 --parallel 4 >>"$LOG" 2>&1 || true
  exit 1
fi

PS2="$("$LMS" ps 2>/dev/null || true)"
N2="$(echo "$PS2" | awk -v m="$MODEL" 'NR>1 && index($0,m){c++} END{print c+0}')"
if [[ "$N2" -lt 1 ]]; then
  log "FAIL model missing after probe"
  exit 1
fi
if [[ "$N2" -gt 1 ]]; then
  log "WARN duplicate instances N=${N2} — collapsing"
  "$LMS" unload --all >>"$LOG" 2>&1 || true
  "$LMS" load "$MODEL" -y -c 8192 --parallel 4 >>"$LOG" 2>&1 || true
fi

TTL_LEFT="$(echo "$PS2" | grep -F "$MODEL" | grep -Eo '[0-9]+m[[:space:]]*/[[:space:]]*[0-9]+h' || true)"
if [[ -n "$TTL_LEFT" ]]; then
  log "WARN still TTL-bound (${TTL_LEFT})"
fi

log "PASS ${MODEL} single-load chat ok content=$(echo "$CONTENT" | tr '\n' ' ' | head -c 40)"
exit 0
