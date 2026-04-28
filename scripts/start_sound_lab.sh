#!/usr/bin/env bash
# Garden / sound-lab — Vite on 127.0.0.1:5173 (Aster on 8787 reverse-proxies here).
# Repo root:  bash scripts/start_sound_lab.sh
#
# TELEMETRY_PORT is read by Vite (default 8788) for /api → telemetry stub.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/ui/sound-lab"

npm install
export TELEMETRY_PORT="${TELEMETRY_PORT:-8788}"
exec npx vite --port 5173 --host 127.0.0.1
