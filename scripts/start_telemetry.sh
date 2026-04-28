#!/usr/bin/env bash
# Telemetry FastAPI stub (default port 8788 — leaves :8787 for Aster Router).
# Repo root:  bash scripts/start_telemetry.sh
#
# expects TELEMETRY_PORT already exported for consistency with Vite; defaults to 8788
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${ROOT}/ui/sound-lab/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ENV_FILE"
  set +a
fi

PORT="${TELEMETRY_PORT:-8788}"
export TELEMETRY_PORT="$PORT"

UV="${ROOT}/.venv/bin/uvicorn"
if [[ ! -x "$UV" ]]; then
  UV=uvicorn
fi
if ! command -v "$UV" >/dev/null 2>&1; then
  echo "telemetry: uvicorn not found. Try:  cd ${ROOT} && python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn" >&2
  exit 1
fi

exec "$UV" telemetry.main:app --host 127.0.0.1 --port "${PORT}" --reload
