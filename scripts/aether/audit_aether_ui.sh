#!/usr/bin/env bash
# Static audit for aether.html — catches regressions introduced in UI patches.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HTML="$ROOT/grid-sovereign-runtime/gateway/static/aether.html"
fail() { echo "AUDIT FAIL: $*"; exit 1; }

rg -q 'tradeDateLocal\(\)' "$HTML" || fail "missing tradeDateLocal"
rg 'anchorTradeDate' "$HTML" | rg -q 'tradeDateLocal' && fail "anchorTradeDate must not call tradeDateLocal()"

python3 <<PY
from pathlib import Path
js=Path("$HTML").read_text().split('<script>',1)[1].split('</script>',1)[0]
a=js.find('serverLaneSnap=laneSnapshotFromBoot')
b=js.find('let serverLaneSnap')
if a>=0 and b>=0 and a<b:
    raise SystemExit('serverLaneSnap assigned before let — strict mode crash')
if js.count('{')!=js.count('}'):
    raise SystemExit(f'brace mismatch {{={js.count("{")} }}={js.count("}")}')
if 'pickEventsForToday' not in js:
    raise SystemExit('missing pickEventsForToday')
if 'if(!drop.has(e.kind)) return !seen.has(e.id)&&seen.add(e.id)' in js:
    raise SystemExit('applyServerLanes double-dedup drops non-lane events')
print('static audit ok')
PY

bash "$ROOT/scripts/aether/verify_aether_ui.sh"
echo "AUDIT ALL PASSED"
