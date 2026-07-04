#!/usr/bin/env bash

set -euo pipefail

echo "Initializing Grid Node..."

mkdir -p models compiler app config logs

if [ ! -f config/grid.yaml ]; then
  cat > config/grid.yaml << 'EOF'
model:
  name: "llama3"
ollama:
  host: "127.0.0.1"
  port: 11434
grid_anchor:
  truth_filter: true
EOF
fi

chmod +x scripts/init_grid.sh || true

echo "Check if Ollama is running: ollama list | grep llama3"
echo "If missing, pull model with: ollama pull llama3"

echo "Starting Grid Router on port 8787..."
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:8b}"
uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1

echo "Grid Node is active at http://127.0.0.1:8787/health"

