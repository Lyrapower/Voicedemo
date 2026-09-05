#!/usr/bin/env bash
# Scout land watchdog — every 10m in shift windows: if GLM final missing or FAIL stamp, run integrity.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCOUT="${ROOT}/grid-scout"
LOG_DIR="${HOME}/Library/Logs/demo-grid"
mkdir -p "$LOG_DIR" "${SCOUT}/state"
LOG="${LOG_DIR}/scout-land-watchdog.log"
ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG" >/dev/null; }

HOUR="$(date +%H)"
MIN="$(date +%M)"
NOW=$((10#$HOUR * 60 + 10#$MIN))
# morning 06:40–08:40 · midday 10:35–11:40 · earnings 12:30–13:40 · evening 21:00–22:10
in_window=0
if (( NOW >= 6 * 60 + 40 && NOW <= 8 * 60 + 40 )); then in_window=1; fi
if (( NOW >= 10 * 60 + 35 && NOW <= 11 * 60 + 40 )); then in_window=1; fi
if (( NOW >= 12 * 60 + 30 && NOW <= 13 * 60 + 40 )); then in_window=1; fi
if (( NOW >= 21 * 60 && NOW <= 22 * 60 + 10 )); then in_window=1; fi
FAIL_STAMP="${SCOUT}/state/land_FAIL"
if [[ -f "$FAIL_STAMP" ]]; then in_window=1; fi
if [[ "$in_window" -ne 1 ]]; then
  exit 0
fi

export PATH="/usr/bin:/bin:/usr/sbin:/Library/Frameworks/Python.framework/Versions/3.13/bin:${PATH:-}"
DAY="$(python3 - <<'PY'
import sys
sys.path.insert(0, "/Users/ciciwang/Projects/demo/grid-scout")
import fetchers
print(fetchers.trading_date().isoformat())
PY
)"

need=0
[[ -f "$FAIL_STAMP" ]] && need=1

due=""
if (( NOW >= 6 * 60 + 50 )); then due="${due} morning"; fi
if (( NOW >= 10 * 60 + 55 )); then due="${due} midday"; fi
if (( NOW >= 12 * 60 + 50 )); then due="${due} earnings"; fi

for mode in $due; do
  jp="${SCOUT}/briefs/${DAY}-${mode}.json"
  final="${SCOUT}/briefs/${DAY}-${mode}-final.md"
  hp="${SCOUT}/briefs/${DAY}-${mode}.html"
  if [[ ! -f "$jp" || ! -f "$final" || ! -f "$hp" ]]; then need=1; continue; fi
  if ! grep -q 'review_origin=glm52_cloud' "$final" 2>/dev/null; then need=1; continue; fi
  if ! grep -q 'review_origin=glm52_cloud' "$hp" 2>/dev/null; then need=1; continue; fi
  if ! grep -q 'GLM 编译终稿' "$hp" 2>/dev/null; then need=1; continue; fi
  python3 - "$jp" <<'PY' || need=1
import json, sys
d = json.load(open(sys.argv[1]))
ds = d.get("ds") or {}
if ds.get("_parse_failed"):
    raise SystemExit(1)
cands = [c for c in (ds.get("candidates") or []) if isinstance(c, dict) and not c.get("empty")]
assert len(cands) >= 1
PY
done

if (( NOW >= 21 * 60 )); then
  ef="${SCOUT}/briefs/${DAY}-evening-final.md"
  if [[ ! -f "$ef" ]] || ! grep -q 'review_origin=glm52_cloud' "$ef" 2>/dev/null; then
    need=1
  fi
fi

if [[ "$need" -eq 0 ]]; then
  log "ok day=${DAY} due=${due} (no action)"
  exit 0
fi

log "NEED repair day=${DAY} fail_stamp=$([[ -f $FAIL_STAMP ]] && echo yes || echo no) due=${due} → integrity"
bash "${ROOT}/scripts/scout_land_integrity.sh" >>"$LOG" 2>&1
rc=$?
log "integrity exit=${rc}"
exit "$rc"
