#!/usr/bin/env bash
# Start Quant Framework Streamlit dashboard (http://localhost:8501)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
  .venv/bin/pip install -e ".[dev]" -q
fi

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
PORT="${DASHBOARD_PORT:-8501}"
echo "Open http://localhost:${PORT} in your browser"
echo "(Keep this terminal open while using the dashboard.)"
exec .venv/bin/python -m streamlit run src/quant_framework/dashboard/app.py \
  --server.port "${PORT}" \
  --server.address 127.0.0.1 \
  --browser.gatherUsageStats false \
  --server.headless true
