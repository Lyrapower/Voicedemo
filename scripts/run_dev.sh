#!/usr/bin/env bash
# TripPack local dev: SQLite in trippack_api/data/dev.db (no Docker).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/trippack_api"
if [ -z "${DATABASE_URL:-}" ]; then
  mkdir -p data
  export DATABASE_URL="sqlite:///data/dev.db"
fi
export DEMO_MODE="${DEMO_MODE:-0}"
export DEMO_CHECK_INTERVAL_MIN="${DEMO_CHECK_INTERVAL_MIN:-2}"
python3 -m pip install -q -r requirements.txt
alembic upgrade head
echo "API: http://127.0.0.1:8810"
echo "Dev UI (visual proof, 20 rows): http://127.0.0.1:8810/ui/dev"
echo "DATABASE_URL=$DATABASE_URL"
exec uvicorn app.main:app --host 0.0.0.0 --port 8810
