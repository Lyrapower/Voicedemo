#!/usr/bin/env bash
# Seam S1 — factor snapshot via alpha api container (sole SQLite writer).
set -euo pipefail
ROOT="/Users/ciciwang/Projects/demo"
CTR="${ALPHA_SEAMS_CTR:-alpha-platform-api-1}"
INBOX="$ROOT/grid-scout/inbox"
mkdir -p "$INBOX"
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
docker cp "$ROOT/alpha-platform/backend/export_factor_snapshot.py" "$CTR:/app/export_factor_snapshot.py"
docker exec \
  -e PLATFORM_DB=/data/platform.db \
  -e SP500_SYMBOLS_CACHE=/data/sp500_symbols.json \
  -e ALPHA_PLATFORM_API_PROCESS=1 \
  "$CTR" python /app/export_factor_snapshot.py \
  --out /tmp/factor_snapshot.json \
  "$@"
docker cp "$CTR:/tmp/factor_snapshot.json" "$INBOX/factor_snapshot.json"
echo "[factor-snapshot] host inbox ← $INBOX/factor_snapshot.json"
