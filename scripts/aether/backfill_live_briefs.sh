#!/usr/bin/env bash
# Backfill production aether_brief for missing trading days (live log source).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${ROOT}/aether_nexus/.venv/bin/python"
START="${1:-2026-07-10}"
END="${2:-2026-07-14}"

export POST_MARKET_LIVE=1
export NEXUS_LIVE_LOG=1
unset POST_MARKET_SUMMARY_DRY_RUN

"${PY}" "${ROOT}/scripts/aether/bootstrap_nexus_live_log.py" --from "${START}" --to "${END}"

DATES=(
  2026-07-10
  2026-07-13
  2026-07-14
)

for d in "${DATES[@]}"; do
  if [[ "${d}" < "${START}" || "${d}" > "${END}" ]]; then
    continue
  fi
  echo "=== live brief ${d} ==="
  "${ROOT}/scripts/start_post_market_summary_gated.sh" \
    --once --date "${d}" --force --production
done

echo "=== store briefs ==="
sqlite3 "${ROOT}/grid-sovereign-runtime/data/grid_store.db" \
  "SELECT id, kind, json_extract(payload,'$.date') FROM events WHERE source='aether' AND kind IN ('aether_brief','aether_brief_dryrun') ORDER BY id DESC LIMIT 10;"
