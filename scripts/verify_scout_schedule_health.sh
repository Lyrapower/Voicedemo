#!/usr/bin/env bash
# Scout schedule health — prove 06:45 morning / 21:00 evening / integrity are loaded
# and today's land artifacts match wall-clock expectations. Exit non-zero on holes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCOUT="${ROOT}/grid-scout"
UID_NUM="$(id -u)"
fail=0
ok() { printf 'OK  %s\n' "$*"; }
bad() { printf 'BAD %s\n' "$*"; fail=1; }

DAY="$(python3 - <<'PY'
import sys
sys.path.insert(0, "/Users/ciciwang/Projects/demo/grid-scout")
import fetchers
print(fetchers.trading_date().isoformat())
PY
)"
HOUR="$(date +%H)"
MINUTE="$(date +%M)"
NOW_MIN=$((10#$HOUR * 60 + 10#$MINUTE))

echo "=== scout schedule health · trading_day=${DAY} · local=$(date '+%Y-%m-%d %H:%M:%S %Z') ==="

for L in com.grid.morning-brief com.grid.evening-brief com.grid.scout-land-integrity com.grid.scout-land-watchdog; do
  if launchctl print "gui/${UID_NUM}/${L}" >/tmp/scout_la_${L}.txt 2>&1; then
    if grep -q 'state = ' "/tmp/scout_la_${L}.txt"; then
      ok "launchd loaded ${L}"
    else
      bad "launchd print odd for ${L}"
    fi
  else
    bad "launchd NOT loaded ${L}"
  fi
done

# Calendar anchors
if launchctl print "gui/${UID_NUM}/com.grid.morning-brief" 2>/dev/null | grep -q '"Hour" => 6' \
  && launchctl print "gui/${UID_NUM}/com.grid.morning-brief" 2>/dev/null | grep -q '"Minute" => 45'; then
  ok "morning calendar 06:45"
else
  bad "morning calendar not 06:45"
fi
if launchctl print "gui/${UID_NUM}/com.grid.evening-brief" 2>/dev/null | grep -q '"Hour" => 21' \
  && launchctl print "gui/${UID_NUM}/com.grid.evening-brief" 2>/dev/null | grep -q '"Minute" => 0'; then
  ok "evening calendar 21:00 (9pm — not 09:00)"
else
  bad "evening calendar not 21:00"
fi
if launchctl print "gui/${UID_NUM}/com.grid.scout-land-integrity" 2>/dev/null | grep -q '"Hour" => 7'; then
  ok "integrity calendar includes 07:15"
else
  bad "integrity calendar missing 07:15"
fi

# Qwen substrate (Grid) — models list ≠ loaded
export PATH="${HOME}/.lmstudio/bin:${PATH}"
if command -v lms >/dev/null 2>&1; then
  if lms ps 2>/dev/null | grep -qi 'qwen/qwen3.5-9b'; then
    ok "qwen/qwen3.5-9b loaded in LM Studio"
  else
    bad "qwen/qwen3.5-9b NOT loaded — run scripts/ensure_qwen_substrate.sh"
  fi
else
  bad "lms CLI missing"
fi

# Scout DS model must exist on Ollama (cloud tag)
if curl -sf --max-time 5 http://127.0.0.1:11434/api/tags \
  | python3 -c 'import json,sys; ns=[m.get("name") for m in json.load(sys.stdin).get("models",[])];
raise SystemExit(0 if any("deepseek-v4-pro" in (n or "") for n in ns) else 1)'; then
  ok "ollama has deepseek-v4-pro:cloud"
else
  bad "ollama MISSING deepseek-v4-pro:cloud — scout 06:45 will empty-fail"
fi

# Env gate that prevented Aug11 gray-card class
if launchctl print "gui/${UID_NUM}/com.grid.morning-brief" 2>/dev/null | grep -q 'DS_MAX_TOKENS => 12000'; then
  ok "morning DS_MAX_TOKENS=12000"
else
  bad "morning DS_MAX_TOKENS missing/not 12000"
fi

JP="${SCOUT}/briefs/${DAY}-morning.json"
HP="${SCOUT}/briefs/${DAY}-morning.html"
EP="${SCOUT}/briefs/${DAY}-evening.html"
RP="${SCOUT}/briefs/${DAY}-review.json"

# After 06:50 expect morning land; after 21:10 expect evening; after 21:25 expect review
if (( NOW_MIN >= 6 * 60 + 50 )); then
  if [[ -f "$JP" ]]; then
    python3 - <<PY || bad "morning.json invalid/no candidates"
import json
d=json.load(open("$JP"))
ds=d.get("ds") or {}
cands=[c for c in (ds.get("candidates") or []) if isinstance(c,dict) and not c.get("empty")]
assert len(cands)>=1
print("cands", len(cands))
PY
    ok "morning.json present with candidates"
  else
    bad "morning.json MISSING after 06:50 — integrity 07:15 should repair; investigate now"
  fi
  [[ -f "$HP" ]] && ok "morning.html present" || bad "morning.html MISSING after 06:50"
else
  ok "pre-06:50: morning land not yet due (files may be prior repair only)"
fi

if (( NOW_MIN >= 21 * 60 + 10 )); then
  [[ -f "$EP" ]] && ok "evening.html present" || bad "evening.html MISSING after 21:10"
  [[ -f "$RP" ]] && ok "review.json present" || bad "review.json MISSING after 21:10 (Aug11 class hole)"
else
  ok "pre-21:10: evening/review not yet due"
fi

# Store emit soft check after morning due
if (( NOW_MIN >= 6 * 60 + 50 )); then
  EMIT="$(curl -sS -m 8 'http://127.0.0.1:8501/store/events/recent?source=aether&kinds=aether_scout_brief&per_kind=6' 2>/dev/null | python3 -c "
import json,sys
day='$DAY'
try: d=json.load(sys.stdin)
except Exception: print('0'); raise SystemExit
arr=d if isinstance(d,list) else d.get('events') or d.get('items') or []
ok=0
for e in arr:
  p=e.get('payload') or e
  if str(p.get('date') or '')[:10]==day and str(p.get('mode') or '')=='morning':
    ok=1
print(ok)
" 2>/dev/null || echo 0)"
  if [[ "$EMIT" == "1" ]]; then ok "store aether_scout_brief morning for ${DAY}"
  else bad "store OPTION emit missing for ${DAY} morning"
  fi
fi

echo "=== result fail=${fail} ==="
exit "$fail"
