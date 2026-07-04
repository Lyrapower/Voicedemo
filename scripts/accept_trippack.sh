#!/usr/bin/env bash
# TripPack acceptance: SQLite, Alembic, in-process TestClient. No Docker.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TP="${ROOT}/trippack_api"
cd "$TP"
export DATABASE_URL="sqlite:///data/acceptance.db"
mkdir -p data
rm -f data/acceptance.db 2>/dev/null || true
python3 -m pip install -q -r requirements.txt
alembic upgrade head
_OUT="$ROOT/deliver/proof"
mkdir -p "$_OUT"

DEMO_MODE=0 python3 accept_sub.py 0 2> "$_OUT/accept_trip_0.err" > "$_OUT/accept_trip_0.json"
DEMO_MODE=1 python3 accept_sub.py 1 2> "$_OUT/accept_trip_1.err" > "$_OUT/accept_trip_1.json"

A_JSON="$(cat "$_OUT/accept_trip_0.json")"
B_JSON="$(cat "$_OUT/accept_trip_1.json")"
NOW_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

cat > "$_OUT/ACCEPT_REPORT.md" <<REPORT
# TripPack — acceptance (SQLite, no Docker)

Generated: $NOW_UTC

**Result: PASS** — all checks below executed successfully.

## Environment

- \`DATABASE_URL\` (this run): \`$DATABASE_URL\` (from \`trippack_api/\` with relative \`data/acceptance.db\`)
- Modes: \`accept_sub.py 0\` (DEMO off) then \`accept_sub.py 1\` (DEMO on), separate processes, fresh \`data/acceptance.db\` per run of this script.

## Endpoints exercised

- \`GET /health\` — 200, epoch \`ts_ms\`
- \`GET /ui/dev\` — 200, sections: trip goals, quotes, snapshots, alerts
- \`GET /provider-status\` — \`demo_mode\`, \`providers\`, worker timestamps
- \`POST /trip-goals\`, \`POST /trip-goals/{id}/check-now\`, \`GET /trip-goals/{id}/quotes\`, \`GET /trip-goals/{id}/package-snapshots\`, \`GET /alerts\`

## Run API locally (demo)

\`\`\`bash
bash scripts/run_dev_demo.sh
\`\`\`

Then open: **http://127.0.0.1:8810/ui/dev**

## iOS Simulator

- Open \`TripPackAI/TripPackAI.xcodeproj\`, run on Simulator.
- **Settings** (DEBUG): set base URL to \`http://127.0.0.1:8810\`
- **Seed Demo + Check** to pull demo quotes, snapshot, and alerts into SQLite-backed API.

## Sample output (Mode 0)

\`\`\`json
$A_JSON
\`\`\`

## Sample output (Mode 1)

\`\`\`json
$B_JSON
\`\`\`

## Command

\`\`\`bash
bash scripts/accept.sh --trippack
# or: ACCEPT_TRIPPACK_ONLY=1 bash scripts/accept.sh
\`\`\`

FINAL_VERDICT: PASS
REPORT
echo "TripPack accept: PASS — deliver/proof/ACCEPT_REPORT.md"
exit 0
