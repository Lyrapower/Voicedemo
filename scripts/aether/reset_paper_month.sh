#!/usr/bin/env bash
# Reset paper month experiment — fresh $1000, empty positions (mock only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATE="${ROOT}/aether-paper/state"
mkdir -p "${STATE}"

rm -f "${STATE}/account.json" "${STATE}/decisions.jsonl" "${STATE}/processed_signals.json" "${STATE}/heartbeat.json"
rm -f "${STATE}/signal_inbox.jsonl"

PY="${ROOT}/aether_nexus/.venv/bin/python"
cd "${ROOT}/aether-paper"
"${PY}" -c "
from paper.store import init_experiment
init_experiment(days=30, start_equity=1000.0)
print('experiment reset — fresh \$1000 month')
"

echo "OK — paper state cleared; inbox preserved if present"
