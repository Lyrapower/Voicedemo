#!/usr/bin/env bash
# Local Ollama :11434 — coder substrate for compile/task routes on :8501
set -euo pipefail

OLLAMA_BIN="${OLLAMA_BIN:-}"
if [[ -z "$OLLAMA_BIN" ]]; then
  if command -v ollama >/dev/null 2>&1; then
    OLLAMA_BIN="$(command -v ollama)"
  elif [[ -x /Applications/Ollama.app/Contents/Resources/ollama ]]; then
    OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
  elif [[ -x /usr/local/bin/ollama ]] && /usr/local/bin/ollama --version >/dev/null 2>&1; then
    OLLAMA_BIN="/usr/local/bin/ollama"
  fi
fi

if [[ -z "${OLLAMA_BIN:-}" ]]; then
  echo "Ollama not found. Install from https://ollama.com/download then re-run:"
  echo "  /Users/ciciwang/Projects/demo/scripts/install_ollama_coder.sh"
  exit 1
fi

if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama already listening on :11434"
  exit 0
fi

echo "Starting Ollama → http://127.0.0.1:11434 ($OLLAMA_BIN serve)"
exec "$OLLAMA_BIN" serve
