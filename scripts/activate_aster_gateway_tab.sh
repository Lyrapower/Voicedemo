#!/usr/bin/env bash
# Quit LM Studio → patch Aster tab to gateway generator → reopen.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}:${ROOT}/repo${PYTHONPATH:+:${PYTHONPATH}}"

echo "=== Install gateway plugin (if needed) ==="
bash "$ROOT/scripts/install_aster_gateway_plugin.sh"

echo "=== Quit LM Studio (so config patch is picked up) ==="
osascript -e 'tell application "LM Studio" to quit' 2>/dev/null || true
sleep 2
# Force if still running
pkill -x "LM Studio" 2>/dev/null || true
sleep 1

echo "=== Patch Aster conversation + permissions ==="
python3 "$ROOT/scripts/activate_aster_gateway_tab.py"

echo "=== Reopen LM Studio ==="
open -a "LM Studio"
sleep 3

echo "=== Verify gateway still up ==="
curl -sf http://127.0.0.1:8501/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('gateway', d.get('status'), d.get('model'))"

echo ""
echo "Aster tab should open with generator demo/aster-grid-gateway."
echo "Send one message; if gateway path works, replies route through :8501."
