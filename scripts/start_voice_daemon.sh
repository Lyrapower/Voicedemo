#!/usr/bin/env bash
# Grid Voice daemon → :8504 (ASR/TTS/LLM voice pipeline)
# Process ownership: launchctl com.demo.grid.voice8504 — see PORT_PROCESS_CONVENTION.md
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GS="$ROOT/grid-sovereign-runtime"
PORT=8504

if lsof -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: :${PORT} already in use — use launchctl, do not kill from scripts." >&2
  echo "  GRID_VOICE_SPEC §2.3: initializing → launchctl kill SIGTERM gui/\$(id -u)/com.demo.grid.voice8504" >&2
  echo "  status=ok only → launchctl kickstart -k gui/\$(id -u)/com.demo.grid.voice8504" >&2
  exit 1
fi

cd "$GS"
export PYTORCH_ENABLE_MPS_FALLBACK="${PYTORCH_ENABLE_MPS_FALLBACK:-1}"
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-$GS/data/model_cache/modelscope}"
export HF_HOME="${HF_HOME:-$GS/data/model_cache/huggingface}"
mkdir -p "$MODELSCOPE_CACHE" "$HF_HOME"
echo "Grid voice daemon → http://127.0.0.1:${PORT} · MPS_FALLBACK=${PYTORCH_ENABLE_MPS_FALLBACK} · cache=${MODELSCOPE_CACHE}"
exec python3 gateway/voice_daemon.py
