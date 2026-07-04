#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/../backend"

cd "$BACKEND_DIR"

if [ -d "venv" ]; then
  source venv/bin/activate
fi

echo "Starting Jarvis Copilot backend..."
echo "WebSocket: ws://127.0.0.1:8000/ws"

uvicorn main:app --host 127.0.0.1 --port 8000 --reload

