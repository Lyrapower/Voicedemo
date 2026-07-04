#!/bin/bash

set -e

echo "Setting up Jarvis Copilot backend..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/../backend"

cd "$BACKEND_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f ".env" ]; then
  echo "Enter your Claude API key:"
  read -r API_KEY
  echo "CLAUDE_API_KEY=$API_KEY" > .env
fi

echo "Backend ready."
echo "Next steps:"
echo "  - Open ios-app/JarvisCopilot in Xcode"
echo "  - Add microphone & speech permissions to Info.plist"
echo "  - Run scripts/start.sh to start backend"

