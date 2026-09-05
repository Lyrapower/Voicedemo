#!/usr/bin/env bash
# PM 窗后一次性回报 — 15:35 ET 后执行.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DB="$ROOT/grid-sovereign-runtime/data/grid_store.db"
AP="$ROOT/alpha-platform"
OUT="$ROOT/aether_nexus/docs/PM_REPORT_2026-07-27.md"
today="$(TZ=America/New_York date '+%Y-%m-%d')"
now_et="$(TZ=America/New_York date '+%H:%M')"
hour="${now_et%%:*}"
if (( 10#$hour < 15 || (10#$hour == 15 && 10#${now_et#*:} < 35) )); then
  echo "SKIP: PM 窗未到 (ET $now_et)"
  exit 2
fi

mkdir -p "$(dirname "$OUT")"
{
  echo "# PM Window Report · $today"
  echo
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ) (ET $now_et)"
  echo
  echo "## 1) 三端 PM scan id"
  python3 <<PY
import json, sqlite3, urllib.request, os
db="$DB"
today="$today"
con=sqlite3.connect(f'file:{db}?mode=ro', uri=True)
def latest_bfs():
    row=con.execute(
        "SELECT id,payload FROM events WHERE source='aether' AND kind='aether_scan' "
        "AND json_extract(payload,'$.label')='BFS sp500' "
        "AND json_extract(payload,'$.date')=? AND json_extract(payload,'$.window')='PM' "
        "ORDER BY id DESC LIMIT 1",(today,)).fetchone()
    if row: return row[0], json.loads(row[1])
    return None, None
aeid, ap = latest_bfs()
print(f"- **aether/store**: #{aeid}" if aeid else "- **aether/store**: (none)")
try:
    d=json.load(urllib.request.urlopen('http://127.0.0.1:8600/api/bfs', timeout=5))
    pm=(d.get('windows') or {}).get('PM') or {}
    print(f"- **platform/bfs**: #{pm.get('event_id')}" if pm.get('event_id') else "- **platform/bfs**: (none)")
except Exception as e:
    print(f"- **platform/bfs**: unreachable ({e})")
try:
    d=json.load(urllib.request.urlopen('http://127.0.0.1:8600/api/state', timeout=5))
    print(f"- **platform/state**: scan {d.get('signal',{}).get('scanId')}")
except Exception as e:
    print(f"- **platform/state**: unreachable ({e})")
# watchdog last PM mention
row=con.execute("SELECT id,payload FROM events WHERE kind='aether_watchdog' ORDER BY id DESC LIMIT 3").fetchall()
for rid, raw in row:
    p=json.loads(raw)
    if str(p.get('window','')).upper()=='PM' or 'PM' in str(p):
        print(f"- **watchdog**: #{rid} status={p.get('status')}")
        break
else:
    print("- **watchdog**: (no recent PM row in last 3)")
con.close()
PY
  echo
  echo "## 2) S2 bid/ask 字段级对照"
  python3 <<PY
import json, sqlite3
db="$DB"
con=sqlite3.connect(f'file:{db}?mode=ro', uri=True)
rows=con.execute(
    "SELECT id,payload FROM events WHERE kind='aether_scan' AND id IN (46318,46435) ORDER BY id"
).fetchall()
print("| id | layer | sym | bid | ask |")
print("|---|---|---|---|---|")
for eid, raw in rows:
    p=json.loads(raw)
    for r in (p.get('rows') or [])[:3]:
        print(f"| #{eid} | store scan | {r.get('sym')} | {r.get('bid')} | {r.get('ask')} |")
con.close()
print("\n(Telegram/platform layers: grep dryrun log + platform filtered — manual extend if needed)")
PY
  echo
  echo "## 3) S3 出处 · #46318 vs #46435"
  python3 <<PY
import json, sqlite3, datetime
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York')
db="$DB"
con=sqlite3.connect(f'file:{db}?mode=ro', uri=True)
for eid in (46318, 46435):
    row=con.execute("SELECT ts,payload FROM events WHERE id=?", (eid,)).fetchone()
    if not row: continue
    ts,p=json.loads(row[1]), row[0]
    et=datetime.datetime.fromtimestamp(float(ts), tz=ET)
    print(f"- **#{eid}**: ts={et.strftime('%Y-%m-%d %H:%M ET')} date={p.get('date')} window={p.get('window')} rows={len(p.get('rows') or [])}")
con.close()
print("- **关系**: #46318=当日 dryrun 真实扫描(无 date/window 或时间窗匹配); #46435=带 date/window 的 AM backfill(隔离轮).")
PY
  echo
  echo "## 4) SURFACE_DOCTOR"
  if launchctl print "$HOME/Library/LaunchAgents/com.demo.aether.surface-doctor.plist" 2>/dev/null | grep -q 'surface_doctor'; then
    echo "- launchd: loaded"
  else
    echo "- launchd: **未部署** (无 com.demo.aether.surface-doctor.plist)"
  fi
  DOCTOR_STORE_DB="$DB" python3 "$ROOT/aether_nexus/surface_doctor.py" --once --force --window PM 2>&1 | tail -20
  echo
  echo "## 5) git diff --stat"
  git -C "$ROOT" diff --stat
} | tee "$OUT"
echo "Wrote $OUT"
