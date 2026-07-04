#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
read -r HOST PORT API_MODEL <<<"$(python3 -c "
import tomllib
from pathlib import Path
c = tomllib.loads(Path('$ROOT/config/aster.toml').read_text('utf-8'))
ch = c.get('channel', {})
ls = c.get('lm_studio', {})
print(ch.get('host','127.0.0.1'), ch.get('port',8787), ls.get('api_model_id','qwen2.5-1.5b'))
")"

LM_ENV="$ROOT/echo_nodes_interface/config/lm_studio.env"
[[ -f "$LM_ENV" ]] && set -a && source "$LM_ENV" && set +a

for pid in $(lsof -t -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true); do
  kill "${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
done
sleep 0.5

export PYTHONPATH="${ROOT}:${ROOT}/repo${PYTHONPATH:+:${PYTHONPATH}}"
export GARDEN_TTS_ENABLED="${GARDEN_TTS_ENABLED:-1}"
export GARDEN_TTS_BACKEND="${GARDEN_TTS_BACKEND:-auto}"
export GARDEN_KOKORO_MODEL="${GARDEN_KOKORO_MODEL:-$HOME/.cache/kokoro/kokoro-v1.0.int8.onnx}"
export GARDEN_KOKORO_VOICES="${GARDEN_KOKORO_VOICES:-$HOME/.cache/kokoro/voices-v1.0.bin}"
export GARDEN_KOKORO_VOICE="${GARDEN_KOKORO_VOICE:-af_heart}"
export GARDEN_TTS_VOICE="${GARDEN_TTS_VOICE:-Daniel}"
export GARDEN_GATEWAY_URL="${GARDEN_GATEWAY_URL:-http://127.0.0.1:8501}"
export GARDEN_LLM_DIALOGUE="${GARDEN_LLM_DIALOGUE:-1}"
export SUBSTRATE_BACKEND=lmstudio
export LM_STUDIO_BASE_URL="${LM_STUDIO_BASE_URL:-http://127.0.0.1:1234/v1}"
export LM_STUDIO_MODEL="${LM_STUDIO_MODEL:-$API_MODEL}"
cd "${ROOT}/repo"
echo "Aster → http://${HOST}:${PORT} · Garden gateway ${GARDEN_GATEWAY_URL} · LM Studio ${LM_STUDIO_MODEL}"
exec python3 -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"
