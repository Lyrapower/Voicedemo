#!/usr/bin/env bash
# Start Aster after particle runtime on 5173 — port from config/aster.toml.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
read -r PORT <<<"$(python3 -c "import tomllib;print(tomllib.load(open('$ROOT/config/aster.toml','rb')).get('channel',{}).get('port',8787))")"
WAIT_SEC="${GARDEN_WAIT_5173_SEC:-20}"
for ((i=0; i<WAIT_SEC; i++)); do
  lsof -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 1
done
if ! lsof -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  if [[ "${GARDEN_REQUIRE_5173:-0}" == "1" ]]; then
    echo "garden8787: timed out waiting for 5173" >&2
    exit 1
  fi
  echo "garden8787: 5173 not up after ${WAIT_SEC}s; starting 8787 anyway" >&2
fi
exec "$ROOT/scripts/start_aster.sh"
