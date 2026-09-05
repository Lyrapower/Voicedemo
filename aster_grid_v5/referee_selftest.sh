#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

LOCKDIR="$(pwd)/traces/.referee_selftest.lock.d"
for _ in $(seq 1 180); do
  if mkdir "${LOCKDIR}" 2>/dev/null; then
    trap 'rmdir "${LOCKDIR}" 2>/dev/null || true' EXIT INT TERM
    break
  fi
  sleep 1
done
if [[ ! -d "${LOCKDIR}" ]]; then
  echo "FAIL: referee_selftest lock timeout" >&2
  exit 1
fi

python3 cloud_boundary.py
python3 provenance_registry.py selftest
python3 sentinel_ledger_v5.py selftest
python3 cc_cli_guard.py selftest
python3 aster_fable_bridge_v5.py selftest
python3 jarvis_backend_runtime_v5.py selftest
python3 frontend_multimodal_v5.py selftest
python3 telegram_aster_fable_bot_v5.py selftest
python3 aether_router_v5.py selftest

echo "PASS: referee_selftest"
