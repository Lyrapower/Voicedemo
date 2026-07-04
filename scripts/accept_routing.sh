#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

required_paths=(
  "knowledge/source/ASTER.md"
  "config/routing_policy.yaml"
  "budgets.yaml"
  "app/adapters/claude_adapter.py"
  "app/adapters/aster_adapter.py"
  "app/router/review_pipeline.py"
  "app/router/compiled_memory.py"
  "scripts/compile_memory.sh"
  "app/main.py"
)

for path in "${required_paths[@]}"; do
  [[ -f "$path" ]] || { echo "FAIL: missing $path"; exit 1; }
done

bash scripts/compile_memory.sh >/dev/null

compiled_paths=(
  "knowledge/compiled/MEMORY.md"
  "knowledge/compiled/WORKSPACE_trading.md"
  "knowledge/compiled/WORKSPACE_crypto.md"
  "knowledge/compiled/WORKSPACE_infra.md"
  "knowledge/compiled/WORKSPACE_senior.md"
)

for path in "${compiled_paths[@]}"; do
  [[ -f "$path" ]] || { echo "FAIL: missing $path"; exit 1; }
done

python3 -m app.main >/tmp/jarvis_routing_accept.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
sleep 3

HEALTH="$(curl -s http://127.0.0.1:8686/health)"
HEALTH_JSON="$HEALTH" python3 - <<'PY'
import json
import os
payload = json.loads(os.environ["HEALTH_JSON"])
if payload.get("status") != "ok":
    raise SystemExit(1)
if payload.get("external_enabled") not in (False, 0):
    raise SystemExit(1)
if payload.get("compiled_memory_source") != "knowledge/compiled/*.md":
    raise SystemExit(1)
PY

echo "PASS"
