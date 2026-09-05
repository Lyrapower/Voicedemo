#!/usr/bin/env bash
# One-time: ensure Ollama is installed, running, and qwen2.5-coder is pulled.
# NOTE (2026-08-22): local coder RETIRED — qwen2.5-coder:7b uninstalled from Ollama
# and gateway_config.json `coder_routing_enabled` flipped to false. compile/task
# routes now go dormant (fall back to chat/LM Studio path). This script is kept
# for reference/re-pull if a local coder is ever reinstated (e.g. on a 64GB Mac).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CODER_TAG="${OLLAMA_CODER_MODEL:-qwen2.5-coder:7b}"

resolve_ollama() {
  if command -v ollama >/dev/null 2>&1 && ollama --version >/dev/null 2>&1; then
    command -v ollama
    return 0
  fi
  if [[ -x /Applications/Ollama.app/Contents/Resources/ollama ]]; then
    echo /Applications/Ollama.app/Contents/Resources/ollama
    return 0
  fi
  return 1
}

if ! OLLAMA_BIN="$(resolve_ollama)"; then
  echo "Ollama is not installed (broken /usr/local/bin/ollama symlink is OK to ignore)."
  echo "Install the macOS app from https://ollama.com/download"
  echo "Open Ollama once so it adds the CLI, then re-run:"
  echo "  bash $ROOT/scripts/install_ollama_coder.sh"
  exit 1
fi

export PATH="$(dirname "$OLLAMA_BIN"):$PATH"

if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Starting Ollama in background..."
  nohup "$OLLAMA_BIN" serve >/tmp/ollama-serve.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi

if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama did not start on :11434. Check /tmp/ollama-serve.log"
  exit 1
fi

echo "Pulling coder model: $CODER_TAG (local, no API cost)"
"$OLLAMA_BIN" pull "$CODER_TAG"

echo "Installed models:"
"$OLLAMA_BIN" list

echo
echo "Gateway coder routing expects:"
echo "  ollama_coder_model = $CODER_TAG"
echo "  coder_routes = compile, task"
echo "Reload gateway after config change:"
echo "  launchctl kickstart -k gui/\$(id -u)/com.demo.grid.gateway8501"
