#!/usr/bin/env bash
# MOCK 回退态抽测 — 仅 15:50 ET 后执行(盘中禁止).
# 不 kill HTML 进程;用 STATE_DOWN=1 令 /api/state→503,页面仍 200 并显式标「回退态」.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TS_HOST="${TS_HOST:-cicimacbook-air.tail76db5b.ts.net}"
AP="$ROOT/alpha-platform"
GW_LABEL="gui/$(id -u)/com.demo.grid.gateway8501"
LOG="$ROOT/aether_nexus/logs/mock_fallback_smoke.jsonl"

now_et="$(TZ=America/New_York date '+%H:%M')"
hour="${now_et%%:*}"
min="${now_et#*:}"; min="${min%%:*}"
if (( 10#$hour < 15 || (10#$hour == 15 && 10#$min < 50) )); then
  echo "SKIP: 盘中/未到 15:50 ET (now ET=$now_et) — 禁止执行"
  exit 2
fi

mkdir -p "$(dirname "$LOG")"
ts_iso="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

fail() { echo "FAIL: $*" | tee -a "$LOG"; exit 1; }
ok() { echo "OK: $*" | tee -a "$LOG"; }

check_fallback_page() {
  local url="$1"
  local html
  html="$(curl -sf "$url" | python3 -c "
import sys,re,json
html=sys.stdin.read()
# 静态 HTML 须含回退态接线
need=['fetchState','回退态','MOCK']
miss=[n for n in need if n not in html]
if miss: print(json.dumps({'ok':False,'miss':miss})); raise SystemExit(0)
print(json.dumps({'ok':True,'title':re.search(r'<title>([^<]+)',html).group(1) if re.search(r'<title>',html) else ''}))
")"
  echo "$html" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" || fail "fallback wiring missing on $url"
}

restore() {
  unset AETHER_STATE_DOWN PLATFORM_STATE_DOWN || true
  launchctl kickstart -k "$GW_LABEL" 2>/dev/null || "$ROOT/scripts/start_grid_gateway.sh" &
  sleep 3
  (cd "$AP" && docker compose up -d api worker) >/dev/null 2>&1 || true
  "$ROOT/scripts/tailscale_serve_watchdog.sh" >/dev/null 2>&1 || true
}
trap restore EXIT

ok "start mock fallback smoke @ $ts_iso"

export AETHER_STATE_DOWN=1
export PLATFORM_STATE_DOWN=1
launchctl kickstart -k "$GW_LABEL"
sleep 3
(cd "$AP" && docker compose up -d --force-recreate api)

sleep 2
curl -sf "http://127.0.0.1:8501/health" >/dev/null || fail "8501 health"
curl -sf "http://127.0.0.1:8600/api/health" >/dev/null || fail "8600 health"
code8501="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8501/api/state)"
code8600="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8600/api/state)"
[[ "$code8501" == "503" ]] || fail "8501 /api/state expected 503 got $code8501"
[[ "$code8600" == "503" ]] || fail "8600 /api/state expected 503 got $code8600"

check_fallback_page "http://127.0.0.1:8501/app/aether.html"
check_fallback_page "http://127.0.0.1:8600/app/console_v11.html"

# JS 回退态(无 playwright 时用 mini eval)
python3 <<'PY' || fail "browser fallback banner"
import json, urllib.request
def probe(url):
    html=urllib.request.urlopen(url, timeout=8).read().decode('utf-8','replace')
    assert '回退态' in html and 'setFallbackBanner' in html
    assert 'MOCK 快照' in html or 'MOCK' in html
for u in ['http://127.0.0.1:8501/app/aether.html','http://127.0.0.1:8600/app/console_v11.html']:
    probe(u)
print('fallback wiring ok')
PY

restore
trap - EXIT

# watchdog 无新红:最近一次 BFS watchdog store 事件非 alert
python3 <<PY || fail "watchdog red after restore"
import json, sqlite3, os
db=os.environ.get('WATCHDOG_STORE_DB','${ROOT}/grid-sovereign-runtime/data/grid_store.db')
con=sqlite3.connect(f'file:{db}?mode=ro', uri=True)
row=con.execute("SELECT payload FROM events WHERE kind='aether_watchdog' ORDER BY id DESC LIMIT 1").fetchone()
con.close()
if not row:
    print('watchdog: no row (skip)')
else:
    p=json.loads(row[0])
    st=str(p.get('status','')).lower()
    if st not in ('ok','green',''):
        raise SystemExit(f'watchdog last status={st!r}')
print('watchdog ok')
PY

ok "mock fallback smoke passed"
