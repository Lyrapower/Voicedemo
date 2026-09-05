#!/usr/bin/env bash
# Seam S2 — scout→heat via alpha api container (sole SQLite writer).
set -euo pipefail
ROOT="/Users/ciciwang/Projects/demo"
CTR="${ALPHA_SEAMS_CTR:-alpha-platform-api-1}"
if docker ps --format '{{.Names}}' | grep -qx alpha-platform-worker-1; then
  docker stop alpha-platform-worker-1 >/dev/null
  RESTART_WORKER=1
else
  RESTART_WORKER=0
fi
cleanup() {
  if [[ "${RESTART_WORKER}" == "1" ]]; then
    docker start alpha-platform-worker-1 >/dev/null || true
  fi
}
trap cleanup EXIT
docker start "$CTR" >/dev/null
docker cp "$ROOT/alpha-platform/backend/scout_heat_adapter.py" "$CTR:/app/scout_heat_adapter.py"
docker exec "$CTR" mkdir -p /tmp/scout-briefs
TODAY=$(python3 - <<'PY'
import datetime
from zoneinfo import ZoneInfo
print(datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat())
PY
)
if [[ -f "$ROOT/grid-scout/briefs/${TODAY}-morning.json" ]]; then
  docker cp "$ROOT/grid-scout/briefs/${TODAY}-morning.json" "$CTR:/tmp/scout-briefs/${TODAY}-morning.json"
fi
docker exec \
  -e PLATFORM_DB=/data/platform.db \
  -e SP500_SYMBOLS_CACHE=/data/sp500_symbols.json \
  -e ALPHA_PLATFORM_API_PROCESS=1 \
  -e PLATFORM_DB_DIRECT_WRITE=1 \
  "$CTR" python /app/scout_heat_adapter.py --briefs /tmp/scout-briefs "$@"
