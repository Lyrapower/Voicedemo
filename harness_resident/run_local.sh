#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
ENV_FILE="${GRID_HARNESS_ENV:-$HOME/.config/grid/harness_resident.env}"
if [[ -f "$ENV_FILE" ]]; then set -a; source "$ENV_FILE"; set +a; fi
if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Run: bash install.sh" >&2
  exit 1
fi
source .venv/bin/activate
exec python run_harness.py
