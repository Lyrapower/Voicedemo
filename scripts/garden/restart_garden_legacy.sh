#!/usr/bin/env bash
# Recover :5173 + :8787 for /legacy (clears stale listeners, correct start order).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

free_port() {
  local port=$1
  local pids
  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "clearing stale :${port} (${pids})"
    kill ${pids} 2>/dev/null || true
    sleep 1
  fi
}

free_port 5173
free_port 8787

launchctl kickstart -k "${DOMAIN}/com.demo.garden.fallback5173" 2>/dev/null || {
  echo "fallback5173 not loaded — run: bash ${ROOT}/scripts/garden/install_launchagents.sh"
  exit 1
}
sleep 2
launchctl kickstart -k "${DOMAIN}/com.demo.garden.aster8787"

for _ in $(seq 1 30); do
  lsof -iTCP:8787 -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 1
done

curl -sf "http://127.0.0.1:8787/legacy/health" >/dev/null || {
  echo "8787 legacy health failed — see ~/Library/Logs/demo-garden/aster8787.err.log"
  exit 1
}
curl -sf "http://127.0.0.1:8787/legacy/" -o /dev/null || {
  echo "8787 legacy UI failed — is :5173 up?"
  exit 1
}
echo "8787 legacy ok → http://127.0.0.1:8787/legacy/"
