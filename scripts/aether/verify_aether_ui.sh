#!/usr/bin/env bash
# Acceptance checks for Aether mobile UI invariants.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HTML="$ROOT/grid-sovereign-runtime/gateway/static/aether.html"
GW="${GW:-http://127.0.0.1:8501}"
DB="$ROOT/grid-sovereign-runtime/data/grid_store.db"

fail() { echo "FAIL: $*"; exit 1; }
ok() { echo "OK: $*"; }

curl -sf "$GW/health" >/dev/null || fail "gateway down on $GW"

SOURCE_VER=$(rg -o 'PAGE_VER="[^"]+"' "$HTML" | head -1 | sed 's/PAGE_VER="//;s/"//')
SERVED_VER=$(curl -sf "$GW/app/aether.html" | rg -o 'PAGE_VER="[^"]+"' | head -1 | sed 's/PAGE_VER="//;s/"//')
[[ "$SOURCE_VER" == "$SERVED_VER" ]] || fail "page version mismatch ($SERVED_VER != $SOURCE_VER)"
ok "page version $SERVED_VER served"

curl -sf "$GW/app/aether.html" | rg -q 'renderOffpoolSection\(opool' && fail "crypto/trading still calls renderOffpoolSection"
ok "no renderOffpoolSection in served HTML"

curl -sf "$GW/app/aether.html" | rg -q 'renderScanDualSection' || fail "missing renderScanDualSection"
ok "SCAN dual section present"

curl -sf "$GW/app/aether.html" | rg -q 'Grid \| Sonnet 并列' || fail "missing parallel premarket header"
ok "parallel premarket header present"

curl -sf "$GW/app/aether.html" | rg -q '未入选' || fail "missing unmatched-side 未入选 marker"
curl -sf "$GW/app/aether.html" | rg -q 'CONSENSUS' || fail "missing same-day CONSENSUS marker"
curl -sf "$GW/app/aether.html" | rg -q '两侧数据非同日，不可对比' || fail "missing cross-day comparison warning"
ok "C1 unmatched/consensus/cross-day markers present"

PRIMARY=$(python3 <<PY
import json,re,urllib.request
html=urllib.request.urlopen("$GW/app/aether.html").read().decode()
boot=json.loads(re.search(r'window\.__AETHER_BOOT__=(\[.*?\]);\n(?:window\.__AETHER_SERVE_TS=\d+;\n)?"use strict"',html,re.S).group(1))
brief=sorted([e for e in boot if e['kind'] in ('aether_brief','aether_brief_dryrun')], key=lambda e:(e['payload'].get('date',''),e['id']), reverse=True)
print(brief[0]['payload']['date'], brief[0]['kind'])
PY
)
[[ "$PRIMARY" == "2026-07-14 aether_brief" ]] || fail "primary brief not 2026-07-14 live ($PRIMARY)"
ok "primary brief $PRIMARY"

for kind in aether_premarket_grid aether_premarket_sonnet aether_scan aether_offpool; do
  sqlite3 "$DB" "SELECT 1 FROM events WHERE source='aether' AND kind='$kind' ORDER BY id DESC LIMIT 1;" | rg -q 1 || fail "store missing $kind"
done
ok "store has grid/sonnet/scan/offpool lanes"

curl -sf "$GW/store/pipeline/health" | python3 -c "
import json,sys
ph=json.load(sys.stdin)
for k in ('premarket_grid','premarket_sonnet','offpool'):
    d=(ph.get(k) or {}).get('last_success_date')
    assert d, f'pipeline missing {k} date: {d}'
brief=(ph.get('post_market_daily') or {}).get('last_success_date')
assert brief=='2026-07-14', f'pipeline brief date wrong: {brief}'
print('pipeline dates ok')
"
ok "pipeline health dates"

curl -sf "$GW/store/report/daily/2026-07-14" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('brief_dryrun'), 'daily report missing brief_dryrun for 07-14'
print('daily report dryrun ok')
"
ok "daily report returns 07-14 dryrun"

curl -sf "$GW/app/aether.html" | rg -q 'laneSinceMmdd' || fail "missing R3 since MM-DD helper"
ok "R3 since MM-DD in served HTML"

curl -sf "$GW/app/aether.html" | rg -q 'verdict_bootstrap|dual_leaderboard' || fail "missing E4-B/S1 brief AB fields"
ok "E4-B dual leaderboard hooks present"

curl -sf "$GW/app/aether.html" | rg -q '"crypto_cli","sonnet_earnings"' || fail "boot compaction omits sonnet_earnings wallet"
ok "sonnet_earnings wallet retained in boot snapshot"

[[ "$SOURCE_VER" == "3.2.4" ]] || fail "expected PAGE_VER 3.2.4 got $SOURCE_VER"
ok "page version 3.2.4"
curl -sf "$GW/app/aether.html" | rg -q 'earningsIntegrityBlocked\(earningsEv\)' || fail "earnings banner still couples brief anomalies"
ok "earnings integrity uses own meta only"

curl -sf "$GW/app/aether.html" | rg -q '信息差成本\(世界知识优势\)' || fail "missing info_gap label"
ok "info_gap label 信息差成本(世界知识优势)"

curl -sf "$GW/app/aether.html" | rg -q 'grid_rolling_win_rate|30d胜率' || fail "missing rolling win rate UI"
ok "rolling win rate UI present"

curl -sf "$GW/app/aether.html" | rg -q '样本不足|e4b-insufficient' || fail "missing E4-B insufficient-sample guard"
ok "E4-B insufficient-sample guard present"

echo "ALL CHECKS PASSED"
