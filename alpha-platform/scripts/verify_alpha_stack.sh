#!/usr/bin/env bash
# Alpha + Grid entry smoke — run on Mac after docker/gateway up.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TS_HOST="${TS_HOST:-cicimacbook-air.tail76db5b.ts.net}"
fail=0

check() {
  local name="$1" url="$2"
  if curl -sf -m 8 "$url" >/dev/null; then
    echo "PASS  $name  $url"
  else
    echo "FAIL  $name  $url"
    fail=1
  fi
}

check_code() {
  local name="$1" url="$2" expect="$3"
  local got
  got="$(curl -s -m 8 -o /dev/null -w '%{http_code}' "$url" || echo 000)"
  if [ "$got" = "$expect" ]; then
    echo "PASS  $name  $url  ($got)"
  else
    echo "FAIL  $name  $url  (got $got want $expect)"
    fail=1
  fi
}

echo "=== Alpha stack verify ==="
check "8501 gateway" "http://127.0.0.1:8501/health"
check "8515 b11" "http://127.0.0.1:8515/health"
check "8600 alpha health" "http://127.0.0.1:8600/api/health"
check "8600 alpha pulse" "http://127.0.0.1:8600/api/pulse"
check "8600 alpha state" "http://127.0.0.1:8600/api/state"
check_code "8501 aether" "http://127.0.0.1:8501/app/aether.html" "200"
check_code "8600 console" "http://127.0.0.1:8600/app/#/console" "200"

if command -v tailscale >/dev/null 2>&1; then
  check "ts gateway" "https://${TS_HOST}/health"
  check_code "ts aether" "https://${TS_HOST}/app/aether.html" "200"
  check_code "ts b11" "https://${TS_HOST}/workbench/grid_workbench_b11.html" "200"
  check_code "ts alpha" "https://${TS_HOST}/alpha/app/" "200"
fi

python3 - <<'PY' || fail=1
import json, urllib.request
h = json.load(urllib.request.urlopen("http://127.0.0.1:8600/api/health", timeout=8))
db = h.get("components", {}).get("platform_db", {})
if db.get("status") == "corrupt":
    print("FAIL  platform_db integrity:", db.get("detail", "")[:120])
    raise SystemExit(1)
print("PASS  platform_db integrity")
PY

if [ "$fail" -eq 0 ]; then
  echo "=== ALL PASS ==="
else
  echo "=== FAILED ==="
  exit 1
fi
