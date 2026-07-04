#!/usr/bin/env bash
# Start Aster after particle runtime on 5173 — port from config/aster.toml.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
read -r PORT <<<"$(python3 -c "import tomllib;print(tomllib.load(open('$ROOT/config/aster.toml','rb')).get('channel',{}).get('port',8787))")"
WAIT_SEC="${GARDEN_WAIT_5173_SEC:-90}"
for ((i=0; i<WAIT_SEC; i++)); do
  lsof -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 1
done
exec "$ROOT/scripts/start_aster.sh"
