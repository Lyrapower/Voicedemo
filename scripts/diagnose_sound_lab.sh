#!/usr/bin/env bash
# Quick checks for Garden / sound-lab + telemetry (run from repo root).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${TELEMETRY_PORT:-8788}"

echo "== TELEMETRY_PORT=${PORT} (set TELEMETRY_PORT to match ui/sound-lab/.env) =="
echo ""

echo "-- Port listeners (empty = nothing bound) --"
for p in 5173 "${PORT}" 8787; do
  if command -v lsof >/dev/null 2>&1; then
    echo "Port ${p}:"
    lsof -nP -iTCP:"${p}" -sTCP:LISTEN 2>/dev/null || echo "  (no listener)"
  fi
done
echo ""

echo "-- HTTP probes --"
curl -sS -m 2 "http://127.0.0.1:${PORT}/health" && echo "" || echo "FAIL: telemetry http://127.0.0.1:${PORT}/health (start: bash scripts/start_telemetry.sh)"
echo ""
curl -sS -m 2 "http://127.0.0.1:5173/" -o /dev/null -w "Vite root HTTP %{http_code}\n" || echo "FAIL: Vite http://127.0.0.1:5173/ (start: bash scripts/start_sound_lab.sh)"
echo ""
curl -sS -m 2 "http://127.0.0.1:5173/api/telemetry" | head -c 200 && echo "" || echo "FAIL: proxied /api/telemetry (need Vite + telemetry on ${PORT})"
echo ""

echo "-- Repo root Python (for uvicorn telemetry) --"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  "${ROOT}/.venv/bin/python" -c "import fastapi,uvicorn; print('ok: fastapi+uvicorn')" 2>/dev/null || echo "MISSING: pip install fastapi uvicorn in .venv"
else
  echo "No ${ROOT}/.venv — use system python with fastapi+uvicorn, or create .venv"
fi

echo ""
echo "-- ui/sound-lab deps --"
if [[ -d "${ROOT}/ui/sound-lab/node_modules/vite" ]]; then
  echo "ok: vite installed"
else
  echo "MISSING: cd ui/sound-lab && pnpm install"
fi
