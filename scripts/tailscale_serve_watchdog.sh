#!/usr/bin/env bash
# Tailscale Grid Guardian — root fix for recurring "Tailscale 又断了"
#
# Recurring failure stack (2026-08-12 evidence):
#   1) App UI: AuthURL empty → "auth window cannot open malformed URL"
#      (menu-bar/VPN can stay Connected while open App looks broken)
#   2) TailscaleStartOnLogin=false → after logout/reboot UI/VPN onboarding drifts
#   3) Old watchdog only silently re-bound Serve when https health failed;
#      empty /tmp log; no VPN/BackendState/StartOnLogin enforcement
#
# This guardian (every StartInterval / RunAtLoad):
#   A. Force StartOnLogin=true (defaults)
#   B. Assert shields-up=false
#   C. If BackendState!=Running or VPN not Connected → `tailscale up` + scutil start
#   D. Keep Serve paths (8501/8515/8600/8610/8620) without needless reset
#      / → :8501 · /workbench → :8515 · /alpha → :8600 · /console → :8610 · /ows → :8620
#   E. Durable log under ~/Library/Logs/demo-grid/
#
# Does NOT: change gateway bind, ACL admin, phone apps, or force-reauth.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TS="${TAILSCALE_BIN:-/Applications/Tailscale.app/Contents/MacOS/Tailscale}"
HOST="${TS_HOST:-cicimacbook-air.tail76db5b.ts.net}"
PORT=8501
LOG_DIR="${HOME}/Library/Logs/demo-grid"
LOG="${LOG_DIR}/tailscale-grid-guardian.log"
mkdir -p "$LOG_DIR"

export PATH="/usr/sbin:/usr/bin:/bin:/usr/local/bin:${PATH:-}"

ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG" >/dev/null; }
# keep log bounded (~500KB)
if [[ -f "$LOG" ]] && [[ "$(wc -c <"$LOG" | tr -d ' ')" -gt 500000 ]]; then
  tail -c 200000 "$LOG" >"${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
fi

if [[ ! -x "$TS" ]]; then
  log "FAIL Tailscale.app binary missing: $TS"
  exit 0
fi

# --- A. Start on login (root of post-reboot recurrence) ---
defaults write io.tailscale.ipn.macsys TailscaleStartOnLogin -bool true 2>/dev/null || true

# --- B. Shields must stay OFF on Mac (phone Serve needs inbound on tailnet) ---
"$TS" set --shields-up=false 2>/dev/null || true

# --- C. Backend + VPN ---
STATUS_JSON="$("$TS" status --json 2>/dev/null || true)"
BACKEND="$(printf '%s' "$STATUS_JSON" | python3 -c 'import sys,json
try:
 d=json.load(sys.stdin); print(d.get("BackendState") or "")
except Exception:
 print("")' 2>/dev/null || true)"
ONLINE="$(printf '%s' "$STATUS_JSON" | python3 -c 'import sys,json
try:
 d=json.load(sys.stdin); print((d.get("Self") or {}).get("Online"))
except Exception:
 print("")' 2>/dev/null || true)"
AUTHURL="$(printf '%s' "$STATUS_JSON" | python3 -c 'import sys,json
try:
 d=json.load(sys.stdin); print(repr(d.get("AuthURL") or ""))
except Exception:
 print("?")' 2>/dev/null || true)"
VPN_LINE="$(/usr/sbin/scutil --nc status Tailscale 2>/dev/null | head -1 || true)"

NEED_UP=0
if [[ "$BACKEND" != "Running" ]]; then NEED_UP=1; fi
if [[ "$ONLINE" != "True" ]]; then NEED_UP=1; fi
if [[ "$VPN_LINE" != "Connected" ]]; then NEED_UP=1; fi

if [[ "$NEED_UP" -eq 1 ]]; then
  log "REPAIR backend=${BACKEND:-?} online=${ONLINE:-?} vpn=${VPN_LINE:-?} → tailscale up + scutil start"
  # no flags = bring online without rewriting settings (safe)
  "$TS" up 2>>"$LOG" || true
  /usr/sbin/scutil --nc start Tailscale 2>>"$LOG" || true
  sleep 2
  STATUS_JSON="$("$TS" status --json 2>/dev/null || true)"
  BACKEND="$(printf '%s' "$STATUS_JSON" | python3 -c 'import sys,json
try:
 d=json.load(sys.stdin); print(d.get("BackendState") or "")
except Exception:
 print("")' 2>/dev/null || true)"
  VPN_LINE="$(/usr/sbin/scutil --nc status Tailscale 2>/dev/null | head -1 || true)"
  log "AFTER_UP backend=${BACKEND:-?} vpn=${VPN_LINE:-?}"
fi

# GUI trap: empty AuthURL + open App → "malformed URL". Do NOT open GUI from guardian.
if [[ "$AUTHURL" == "''" || "$AUTHURL" == '""' ]]; then
  : # expected when already logged in
else
  if [[ -n "$AUTHURL" && "$AUTHURL" != "?" ]]; then
    log "WARN AuthURL set (${AUTHURL}) — login pending; GUI open may fail; do not force-reauth from agent"
  fi
fi

# --- D. Local gateway ---
if ! curl -sf --max-time 4 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  log "REPAIR local :${PORT} health fail → kickstart gateway8501"
  launchctl kickstart -k "gui/$(id -u)/com.demo.grid.gateway8501" 2>>"$LOG" || \
    "$ROOT/scripts/start_grid_gateway.sh" >/dev/null 2>&1 &
  sleep 4
fi

ensure_serve_path() {
  local path="$1" target="$2"
  # path "/" checked via root health; others via path health when possible
  if [[ "$path" == "/" ]]; then
    if curl -sf --max-time 6 "https://${HOST}/health" >/dev/null 2>&1; then
      return 0
    fi
    log "REPAIR serve / → ${target}"
    "$TS" serve --bg "$target" 2>>"$LOG" || true
    return 0
  fi
  # try a cheap probe; if path service local is up but serve missing, rebind
  local local_ok=0 serve_ok=0
  case "$path" in
    /workbench) curl -sf --max-time 2 "http://127.0.0.1:8515/health" >/dev/null 2>&1 && local_ok=1 || true
                curl -sf --max-time 4 "https://${HOST}/workbench/" >/dev/null 2>&1 && serve_ok=1 || true ;;
    /alpha)     curl -sf --max-time 2 "http://127.0.0.1:8600/api/health" >/dev/null 2>&1 && local_ok=1 || true
                curl -sf --max-time 4 "https://${HOST}/alpha/" >/dev/null 2>&1 && serve_ok=1 || true ;;
    /console)   curl -sf --max-time 2 "http://127.0.0.1:8610/api/health" >/dev/null 2>&1 && local_ok=1 || true
                curl -sf --max-time 4 "https://${HOST}/console/api/health" >/dev/null 2>&1 && serve_ok=1 || true ;;
    /ows)       curl -sf --max-time 2 "http://127.0.0.1:8620/api/health" >/dev/null 2>&1 && local_ok=1 || true
                curl -sf --max-time 4 "https://${HOST}/ows/api/health" >/dev/null 2>&1 && serve_ok=1 || true ;;
  esac
  if [[ "$local_ok" -eq 1 && "$serve_ok" -eq 0 ]]; then
    log "REPAIR serve ${path} → ${target}"
    "$TS" serve --bg --set-path="$path" "$target" 2>>"$LOG" || true
  fi
}

# If root Serve dead, one reset then rebind all (brief window — only when needed)
if ! curl -sf --max-time 6 "https://${HOST}/health" >/dev/null 2>&1; then
  log "REPAIR MagicDNS /health fail → serve reset + full rebind"
  "$TS" serve reset 2>>"$LOG" || true
  "$TS" serve --bg "http://127.0.0.1:${PORT}" 2>>"$LOG" || true
  "$TS" serve --bg --set-path=/workbench "http://127.0.0.1:8515" 2>>"$LOG" || true
  "$TS" serve --bg --set-path=/alpha "http://127.0.0.1:8600" 2>>"$LOG" || true
  "$TS" serve --bg --set-path=/console "http://127.0.0.1:8610" 2>>"$LOG" || true
  "$TS" serve --bg --set-path=/ows "http://127.0.0.1:8620" 2>>"$LOG" || true
else
  ensure_serve_path / "http://127.0.0.1:${PORT}"
  ensure_serve_path /workbench "http://127.0.0.1:8515"
  ensure_serve_path /alpha "http://127.0.0.1:8600"
  ensure_serve_path /console "http://127.0.0.1:8610"
  ensure_serve_path /ows "http://127.0.0.1:8620"
fi

# Final probe
CODE="$(curl -sS -m 8 -o /dev/null -w '%{http_code}' "https://${HOST}/health" 2>/dev/null || echo 000)"
START_ON="$(defaults read io.tailscale.ipn.macsys TailscaleStartOnLogin 2>/dev/null || echo '?')"
VPN_LINE="$(/usr/sbin/scutil --nc status Tailscale 2>/dev/null | head -1 || true)"
log "OK backend=${BACKEND:-?} vpn=${VPN_LINE:-?} startOnLogin=${START_ON} magic_health=${CODE}"
