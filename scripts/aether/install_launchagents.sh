#!/usr/bin/env bash
# KeepAlive LaunchAgents — full Aether stack (no manual restarts after reboot).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd"
DEST="${HOME}/Library/LaunchAgents"
LOG="${HOME}/Library/Logs/demo-aether"
DOMAIN="gui/$(id -u)"

AGENTS=(
  com.demo.aether.nexus-daemon
  com.demo.aether.nexus-dryrun
  com.demo.aether.nexus8510
  com.demo.aether.watcher-daemon
  com.demo.aether.watcher8520
)
PORTS=(8510 8520)

mkdir -p "${DEST}" "${LOG}"
chmod +x "${ROOT}/scripts/aether/"*.sh

render_plist() {
  local ssl_cert
  ssl_cert="$(python3 -m certifi 2>/dev/null || "${ROOT}/aether_nexus/.venv/bin/python" -m certifi 2>/dev/null || true)"
  sed \
    -e "s|__HOME__|${HOME}|g" \
    -e "s|__DEMO_ROOT__|${ROOT}|g" \
    -e "s|__SSL_CERT_FILE__|${ssl_cert}|g" \
    "$1" >"$2"
}

for label in "${AGENTS[@]}"; do
  if launchctl print "${DOMAIN}/${label}" >/dev/null 2>&1; then
    launchctl bootout "${DOMAIN}" "${DEST}/${label}.plist" 2>/dev/null || true
  fi
done

for port in "${PORTS[@]}"; do
  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping stale listener on :${port} (${pids})"
    kill ${pids} 2>/dev/null || true
    sleep 1
  fi
done

pkill -f "${ROOT}/aether_nexus/aether_daemon.py" 2>/dev/null || true
pkill -f "${ROOT}/aether_nexus/aether_dryrun.py" 2>/dev/null || true
pkill -f "${ROOT}/aether_watcher/aether_watcher.py" 2>/dev/null || true
sleep 1

for label in "${AGENTS[@]}"; do
  render_plist "${SRC}/${label}.plist" "${DEST}/${label}.plist"
done

for label in "${AGENTS[@]}"; do
  launchctl bootstrap "${DOMAIN}" "${DEST}/${label}.plist"
  launchctl enable "${DOMAIN}/${label}"
  launchctl kickstart -k "${DOMAIN}/${label}" || true
done

sleep 6
FAIL=0

echo "=== Aether KeepAlive ==="
for label in "${AGENTS[@]}"; do
  state="$(launchctl print "${DOMAIN}/${label}" 2>/dev/null | grep "state = " | head -1 | sed 's/.*= //' || echo missing)"
  if [[ "${state}" != "running" ]]; then
    echo "  FAIL ${label} state=${state}"
    FAIL=1
  else
    echo "  OK   ${label}"
  fi
done

echo "=== HTTP ==="
for port in "${PORTS[@]}"; do
  code="$(curl -sf --max-time 8 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/" 2>/dev/null || echo 000)"
  if [[ "${code}" != "200" ]]; then
    echo "  FAIL :${port} HTTP ${code}"
    FAIL=1
  else
    echo "  OK   :${port} HTTP ${code}"
  fi
done

echo "=== Watcher heartbeat ==="
ROOT="${ROOT}" python3 - <<'PY' || FAIL=1
import json, os, time, sys
from pathlib import Path
root = Path(os.environ["ROOT"])
hb = json.loads((root / "aether_watcher/state/heartbeat.json").read_text())
age = time.time() - hb.get("ts", 0)
print(f"  heartbeat age={int(age)}s targets={len(hb.get('targets', []))}")
sys.exit(0 if age < 120 else 1)
PY

if [[ "${FAIL}" != "0" ]]; then
  echo "AETHER_INSTALL FAIL — logs: ${LOG}/"
  exit 1
fi
echo "AETHER_INSTALL PASS — survives reboot; no manual run_all.sh needed."
