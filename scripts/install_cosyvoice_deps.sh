#!/usr/bin/env bash
# CosyVoice2 deps for Grid voice daemon (Python 3.13 / macOS MPS).
# Run once after cloning third_party/CosyVoice + submodule Matcha-TTS.
set -euo pipefail
PY="${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.13/bin/python3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GS="$ROOT/grid-sovereign-runtime"
cd "$GS"

echo "CosyVoice2 dependency install (see docs/GRID_VOICE_SPEC.md blockers)"
"$PY" -m pip install torch torchaudio HyperPyYAML omegaconf conformer modelscope soundfile librosa \
  inflect wetext onnxruntime openai-whisper transformers diffusers lightning hydra-core \
  gdown matplotlib wget 'setuptools==69.5.1' peft

if [[ -d third_party/CosyVoice ]]; then
  git -C third_party/CosyVoice submodule update --init --recursive third_party/Matcha-TTS
fi

if [[ ! -d pretrained_models/CosyVoice2-0.5B/cosyvoice2.yaml ]]; then
  echo "Downloading CosyVoice2-0.5B weights..."
  "$PY" -c "
from huggingface_hub import snapshot_download
snapshot_download('FunAudioLLM/CosyVoice2-0.5B', local_dir='pretrained_models/CosyVoice2-0.5B')
"
fi

echo "Probe:"
"$PY" -c "
from pathlib import Path
import sys
repo=Path('third_party/CosyVoice')
for p in [repo/'third_party/Matcha-TTS', repo]: sys.path.insert(0,str(p))
from gateway.voice_engines import VoiceEngines
from gateway.local_gateway import CONFIG
e=VoiceEngines(CONFIG.get('voice') or {})
print(e.health())
"
