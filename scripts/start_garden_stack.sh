#!/usr/bin/env bash
# Garden full stack: LM Studio 9B gateway (8501) + particles (5173) + Aster/Garden (8787)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export PYTHONPATH="${ROOT}:${ROOT}/repo${PYTHONPATH:+:${PYTHONPATH}}"
export GARDEN_GATEWAY_URL="${GARDEN_GATEWAY_URL:-http://127.0.0.1:8501}"
export GARDEN_LLM_DIALOGUE="${GARDEN_LLM_DIALOGUE:-1}"

# 5173 particle UI
for pid in $(lsof -t -iTCP:5173 -sTCP:LISTEN 2>/dev/null || true); do
  kill "${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
done
python3 -m uvicorn scripts.sound_lab_fallback:app --host 127.0.0.1 --port 5173 &
PARTICLE_PID=$!

# 8501 sovereign gateway → LM Studio 9B
"$ROOT/scripts/start_grid_gateway.sh" &
GATEWAY_PID=$!

sleep 2

# 8787 Aster + Garden API
export GARDEN_TTS_ENABLED="${GARDEN_TTS_ENABLED:-1}"
export GARDEN_TTS_BACKEND="${GARDEN_TTS_BACKEND:-auto}"
export SUBSTRATE_BACKEND=lmstudio
export LM_STUDIO_BASE_URL="${LM_STUDIO_BASE_URL:-http://127.0.0.1:1234/v1}"
export LM_STUDIO_MODEL="${LM_STUDIO_MODEL:-qwen/qwen3.5-9b}"

for pid in $(lsof -t -iTCP:8787 -sTCP:LISTEN 2>/dev/null || true); do
  kill "${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
done
sleep 0.5
cd "${ROOT}/repo"
echo "Garden stack:"
echo "  particles  http://127.0.0.1:5173"
echo "  gateway    ${GARDEN_GATEWAY_URL}  → LM Studio 9B"
echo "  garden     http://127.0.0.1:8787"
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8787 &
ASTER_PID=$!

trap 'kill $PARTICLE_PID $GATEWAY_PID $ASTER_PID 2>/dev/null' EXIT
wait $ASTER_PID
