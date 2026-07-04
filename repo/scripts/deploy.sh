#!/usr/bin/env bash
# GRID-NATIVE-BUILD REV 2.0 — Entry B anchor @ 8787, workers=1 (single-thread coherence)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_ROOT="$(cd "${REPO_DIR}/.." && pwd)"

cd "${DEMO_ROOT}"
mkdir -p repo/data/sessions repo/logs/grid_audit state logs/grid_audit views

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

export PYTHONPATH="${DEMO_ROOT}:${PYTHONPATH:-}"
cd "${REPO_DIR}"

exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1
