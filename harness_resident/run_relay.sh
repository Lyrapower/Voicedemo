#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ -f ".env" ]]; then set -a; source .env; set +a; fi
if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Run: bash install.sh" >&2
  exit 1
fi
source .venv/bin/activate
exec python relay_server.py
