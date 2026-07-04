#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 - <<'PY'
from jarvis.trading_local_engine import run_daily_readiness_check
result = run_daily_readiness_check()
print(result["verdict"])
print("required_action:")
for action in result.get("required_action", []):
    print(f"- {action}")
print(f"proof_path: {result.get('proof_path')}")
PY
