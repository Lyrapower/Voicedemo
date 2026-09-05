#!/usr/bin/env bash
# Daily stack acceptance — invoked automatically by schedule_catchup (daily_stack_verify.py).
# Manual run only for dev/debug.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GW="${GW:-http://127.0.0.1:8501}"
DB="$ROOT/grid-sovereign-runtime/data/grid_store.db"
TODAY="${TODAY:-$(TZ=America/New_York date +%F)}"

fail() { echo "FAIL: $*"; exit 1; }
ok() { echo "OK: $*"; }

curl -sf "$GW/health" >/dev/null || fail "8501 gateway down ($GW)"
ok "8501 gateway health"

if command -v tailscale >/dev/null 2>&1; then
  TS_HOST="$(tailscale status --json 2>/dev/null | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  print((d.get('Self') or {}).get('DNSName','').rstrip('.'))
except Exception:
  print('')
" 2>/dev/null || true)"
  if [[ -n "$TS_HOST" ]]; then
    curl -sf "https://${TS_HOST}/health" >/dev/null || fail "Tailscale serve health failed (https://${TS_HOST})"
    ok "Tailscale serve → 8501 (${TS_HOST})"
  else
    echo "WARN: Tailscale DNS unknown — skip remote health"
  fi
fi

launchctl print "gui/$(id -u)/com.demo.grid.gateway8501" 2>/dev/null | rg -q 'state = running' \
  || fail "launchd com.demo.grid.gateway8501 not running"
ok "launchd gateway8501 running"

curl -sf http://127.0.0.1:1234/v1/models >/dev/null || fail "LM Studio :1234 unreachable"
ok "LM Studio :1234"

# Models list ≠ loaded. Require qwen resident (closes IDLE/TTL unload hole).
export PATH="${HOME}/.lmstudio/bin:${PATH}"
if command -v lms >/dev/null 2>&1; then
  lms ps 2>/dev/null | grep -qi 'qwen/qwen3.5-9b' \
    || fail "qwen/qwen3.5-9b NOT loaded in LM Studio (lms ps) — run scripts/ensure_qwen_substrate.sh"
  ok "lms ps has qwen/qwen3.5-9b loaded"
else
  echo "WARN: lms CLI missing — skip loaded-model check"
fi

# Live substrate token (not just /v1/models)
python3 - <<'PY' || fail "qwen chat probe failed on :1234"
import json, urllib.request
body=json.dumps({
  "model":"qwen/qwen3.5-9b",
  "messages":[{"role":"user","content":"reply exactly: ok"}],
  "max_tokens":4,"stream":False,"temperature":0,
}).encode()
req=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions", data=body,
                           headers={"Content-Type":"application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=90) as r:
  d=json.loads(r.read().decode())
content=((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
if not str(content).strip():
  raise SystemExit(1)
print(content.strip()[:40])
PY
ok "qwen :1234 chat probe"

python3 - <<PY || fail "today aether_scan missing in store"
import sqlite3, sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
db = "$DB"
today = "$TODAY"
est = ZoneInfo("America/New_York")
start = datetime.fromisoformat(today).replace(tzinfo=est).timestamp()
end = start + 86400
conn = sqlite3.connect(db)
n = conn.execute(
    "SELECT COUNT(*) FROM events WHERE source='aether' AND kind='aether_scan' AND ts>=? AND ts<?",
    (start, end),
).fetchone()[0]
if n < 1:
    sys.exit(1)
print(n)
PY
ok "store aether_scan for $TODAY"

# Coach intentionally retired 2026-07-23 — only hard-fail when OFFPOOL_COACH_REQUIRED=1
python3 - <<PY || fail "Fable coach store emit missing for $TODAY (REQUIRED=1)"
import os, sqlite3, sys
db = "$DB"
today = "$TODAY"
req = (os.getenv("OFFPOOL_COACH_REQUIRED") or "").strip().lower() in ("1", "true", "yes", "on")
if not req:
    print("SKIP coach store check (OFFPOOL_COACH_STATUS=retired / REQUIRED≠1)")
    raise SystemExit(0)
conn = sqlite3.connect(db)
for w in ("PREMARKET", "EXECUTION"):
    n = conn.execute(
        "SELECT COUNT(*) FROM events WHERE source='aether' AND kind='aether_offpool_coach' "
        "AND json_extract(payload,'$.date')=? AND json_extract(payload,'$.window')=?",
        (today, w),
    ).fetchone()[0]
    if n < 1:
        print("missing", w)
        sys.exit(1)
PY
ok "store aether_offpool_coach (required only if OFFPOOL_COACH_REQUIRED=1)"

cd "$ROOT/aether_nexus"
python3 - <<PY
from post_market_summary_daemon import ground_from_store_scan
g = ground_from_store_scan("$TODAY")
assert g.get("top_symbol"), g
print(g["top_symbol"], g.get("candidate_source"))
PY
ok "post_market ground_from_store_scan has top_symbol"

DAEMON_LOG="$HOME/Library/Logs/demo-aether/nexus-daemon.err.log"
if [[ -f "$DAEMON_LOG" ]]; then
  if rg "IB connection failed" "$DAEMON_LOG" 2>/dev/null | rg -q "$TODAY"; then
    fail "nexus-daemon IB connection failed logged today (dryrun-only should skip IB)"
  fi
fi
ok "nexus-daemon no IB failure spam today"

curl -sf "$GW/app/aether.html" | rg -q 'PAGE_VER=' || fail "aether.html not served"
curl -sf "$GW/app/grid.html" | rg -q 'PAGE_VER=|laneHud|ui ' || fail "grid.html marker missing"
ok "aether.html + grid.html served"

echo "=== ALL PASS ==="
