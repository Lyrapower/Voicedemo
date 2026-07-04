#!/usr/bin/env bash
# Garden v1 API — macOS say/afplay TTS + live telemetry on 8790 (8787/8788 untouched).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${GARDEN_V1_PORT:-8790}"

UV="${ROOT}/.venv/bin/uvicorn"
if [[ ! -x "$UV" ]]; then
  UV=uvicorn
fi
if ! command -v "$UV" >/dev/null 2>&1; then
  echo "garden_v1: uvicorn not found" >&2
  exit 1
fi

export GARDEN_TTS_VOICE="${GARDEN_TTS_VOICE:-Daniel}"
export GARDEN_TTS_RATE="${GARDEN_TTS_RATE:-155}"
export GARDEN_TTS_AUTO_ON_MIC="${GARDEN_TTS_AUTO_ON_MIC:-0}"
# Default off — opt in: GARDEN_TTS_ENABLED=1 bash scripts/start_garden_v1_8790.sh
export GARDEN_TTS_ENABLED="${GARDEN_TTS_ENABLED:-0}"

exec "$UV" repo.telemetry.garden_v1_app:app --host 127.0.0.1 --port "${PORT}"
