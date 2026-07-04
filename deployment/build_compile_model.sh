#!/bin/bash
set -e

echo "Building compile layer model with foundational anchor..."

cd "$(dirname "$0")"

if ! command -v ollama >/dev/null 2>&1; then
    echo "ERROR: ollama not in PATH. Install Ollama, then re-run this script."
    exit 127
fi

# Verify Ollama running
if ! pgrep -x "ollama" > /dev/null; then
    echo "Starting Ollama service..."
    ollama serve &
    sleep 3
fi

# Pull base model if not present
ollama list | grep -q "qwen2.5:32b" || ollama pull qwen2.5:32b

# Build custom model with anchor
ollama create compile_layer -f Modelfile.compile_layer

echo "Build complete. Verify with: ollama run compile_layer"
echo "Tagged as: compile_layer"
