#!/usr/bin/env bash
# Aether Watcher daemon — standalone sidecar (not wired to Jarvis).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
if [[ ! -f .env ]] && [[ -f .env.example ]]; then
  echo "NOTE: copy .env.example → .env and fill notification keys"
fi
exec .venv/bin/python aether_watcher.py
