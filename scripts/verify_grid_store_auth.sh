#!/usr/bin/env bash
# Store 鉴权 curl 探针 — 只读 GET，回报 HTTP 状态码（不写 store）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GW="${GW_URL:-http://127.0.0.1:8501}"
NODE="${STORE_PROBE_NODE:-field-particle}"
URL="${GW}/store/conversations/${NODE}?limit=1"
fail=0

read_token() {
  if [[ -n "${GRID_STORE_TOKEN:-}" ]]; then
    printf '%s' "$GRID_STORE_TOKEN"
    return
  fi
  local f="${ROOT}/grid-sovereign-runtime/config/grid_store.token"
  if [[ -f "$f" ]]; then
    tr -d '[:space:]' < "$f"
  fi
}

http_code() {
  curl -s -o /dev/null -w '%{http_code}' "$@"
}

echo "=== grid store auth probe ==="
echo "  endpoint: GET ${URL}"

if ! curl -sf "${GW}/health" >/dev/null 2>&1; then
  echo "  SKIP  8501 /health unreachable — start gateway first"
  exit 2
fi

code_none=$(http_code "$URL")
echo "  no-token  → HTTP ${code_none}"

TOKEN="$(read_token || true)"
if [[ -z "$TOKEN" ]]; then
  echo "  mode: store auth DISABLED (no GRID_STORE_TOKEN / grid_store.token)"
  if [[ "$code_none" == "200" ]]; then
    echo "  PASS  open store returns 200 without token"
  else
    echo "  FAIL  expected 200 without token, got ${code_none}"
    fail=1
  fi
else
  echo "  mode: store auth ENABLED (token configured)"
  code_bad=$(http_code -H 'X-Grid-Token: grid-store-probe-invalid' "$URL")
  code_ok=$(http_code -H "X-Grid-Token: ${TOKEN}" "$URL")
  echo "  bad-token → HTTP ${code_bad}"
  echo "  good-token → HTTP ${code_ok}"
  if [[ "$code_none" == "401" ]]; then
    echo "  PASS  no-token rejected (401)"
  else
    echo "  FAIL  expected 401 without token, got ${code_none}"
    fail=1
  fi
  if [[ "$code_bad" == "401" ]]; then
    echo "  PASS  bad-token rejected (401)"
  else
    echo "  FAIL  expected 401 for bad token, got ${code_bad}"
    fail=1
  fi
  if [[ "$code_ok" == "200" ]]; then
    echo "  PASS  good-token accepted (200)"
  else
    echo "  FAIL  expected 200 for good token, got ${code_ok}"
    fail=1
  fi
fi

exit "$fail"
