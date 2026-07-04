#!/usr/bin/env bash
set -euo pipefail
CACHE="${HOME}/.cache/kokoro"
mkdir -p "$CACHE"
pip3 install -U kokoro-onnx
if [[ ! -f "$CACHE/kokoro-v1.0.int8.onnx" ]]; then
  curl -fsSL -o "$CACHE/kokoro-v1.0.int8.onnx" \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx"
fi
if [[ ! -f "$CACHE/voices-v1.0.bin" ]]; then
  curl -fsSL -o "$CACHE/voices-v1.0.bin" \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
fi
echo "Kokoro ready: $CACHE"
python3 - <<'PY'
from pathlib import Path
from kokoro_onnx import Kokoro
c = Path.home() / ".cache/kokoro"
Kokoro(str(c / "kokoro-v1.0.int8.onnx"), str(c / "voices-v1.0.bin"))
print("kokoro_onnx load ok")
PY
