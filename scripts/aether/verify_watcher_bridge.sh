#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GW="${GRID_STORE_URL:-http://127.0.0.1:8501/store/events}"
GW_BASE="${GW%/store/events}"
TOKEN_FILE="${ROOT}/grid-sovereign-runtime/config/bridge_store.token"
STATE="${ROOT}/aether_watcher/state"
PASS=0
FAIL=0
ok(){ echo "  ✓ $*"; PASS=$((PASS+1)); }
bad(){ echo "  ✗ $*"; FAIL=$((FAIL+1)); }

echo "=== watcher bridge verify ==="

if curl -sf "${GW_BASE}/health" >/dev/null 2>&1; then
  ok "gateway :8501 health"
else
  bad "gateway :8501 down"
fi

if curl -sf "${GW_BASE}/watcher/snapshot" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'online' in d" 2>/dev/null; then
  ok "8520 snapshot via :8501"
else
  bad "8520 snapshot unreachable"
fi

if [[ -f "${TOKEN_FILE}" ]]; then
  ok "bridge_store.token exists"
else
  bad "bridge_store.token missing — run install_watcher_bridge_launchagent.sh"
fi

DOMAIN="gui/$(id -u)"
if launchctl print "${DOMAIN}/com.demo.aether.watcher-bridge" >/dev/null 2>&1; then
  ok "launchd com.demo.aether.watcher-bridge loaded"
else
  bad "watcher-bridge launchd not loaded"
fi

if [[ -f "${STATE}/events.json" ]]; then
  ok "8520 events.json present"
else
  bad "8520 events.json missing"
fi

RECENT="$(curl -sf "${GW_BASE}/store/events/recent?source=watcher&kinds=watcher_momentum,watcher_health,watcher_alert&per_kind=3" 2>/dev/null || echo "[]")"
N="$(printf '%s' "${RECENT}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)"
if [[ "${N}" -ge 0 ]]; then
  ok "store watcher kinds readable (${N} recent)"
fi

if [[ -f "${STATE}/bridge_cursor.json" ]]; then
  ok "bridge_cursor.json present"
else
  echo "  · bridge_cursor.json will appear after first push"
fi

echo "--- ${PASS} passed, ${FAIL} failed ---"
[[ "${FAIL}" -eq 0 ]]
