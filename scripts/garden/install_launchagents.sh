#!/usr/bin/env bash
# Install core demo LaunchAgents — unified KeepAlive for :8501 gateway + :8787 Aster (+ garden stack).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/garden/launchd"
DEST="${HOME}/Library/LaunchAgents"
LOG_GARDEN="${HOME}/Library/Logs/demo-garden"
LOG_GRID="${HOME}/Library/Logs/demo-grid"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3)"
fi
UVICORN="/Library/Frameworks/Python.framework/Versions/3.13/bin/uvicorn"
if [[ ! -x "${UVICORN}" ]]; then
  UVICORN="$(command -v uvicorn)"
fi

# Core Aster chain: gateway substrate door + telemetry/orchestration
CORE_AGENTS=(
  com.demo.grid.gateway8501
  com.demo.garden.aster8787
)
CORE_PORTS=(8501 8787)

# Optional garden stack (particles + telemetry sidecar)
GARDEN_AGENTS=(
  com.demo.garden.fallback5173
  com.demo.garden.telemetry8788
)
GARDEN_PORTS=(5173 8788)

INSTALL_GARDEN="${INSTALL_GARDEN_STACK:-1}"
if [[ "${INSTALL_GARDEN}" == "0" ]]; then
  AGENTS=("${CORE_AGENTS[@]}")
  PORTS=("${CORE_PORTS[@]}")
else
  AGENTS=("${CORE_AGENTS[@]}" "${GARDEN_AGENTS[@]}")
  PORTS=("${CORE_PORTS[@]}" "${GARDEN_PORTS[@]}")
fi

mkdir -p "${DEST}" "${LOG_GARDEN}" "${LOG_GRID}"
chmod +x "${ROOT}/scripts/garden/start_aster_8787.sh" "${ROOT}/scripts/garden/start_aster_8787.py"
chmod +x "${ROOT}/scripts/start_grid_gateway.sh"

stop_port_listeners() {
  local port=$1
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local pids
  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping stale listener(s) on :${port} (${pids})"
    kill ${pids} 2>/dev/null || true
    sleep 1
  fi
}

render_plist() {
  local src_file=$1 dest_file=$2
  sed \
    -e "s|__HOME__|${HOME}|g" \
    -e "s|__DEMO_ROOT__|${ROOT}|g" \
    -e "s|__PYTHON__|${PYTHON}|g" \
    -e "s|__UVICORN__|${UVICORN}|g" \
    "${src_file}" > "${dest_file}"
}

bootout_if_loaded() {
  local label=$1
  local dest_file="${DEST}/${label}.plist"
  if launchctl print "${DOMAIN}/${label}" >/dev/null 2>&1; then
    launchctl bootout "${DOMAIN}" "${dest_file}" 2>/dev/null || true
  fi
}

echo "Installing demo LaunchAgents (ROOT=${ROOT}) → ${DEST}"
for label in "${AGENTS[@]}"; do
  bootout_if_loaded "${label}"
done
for port in "${PORTS[@]}"; do
  stop_port_listeners "${port}"
done
for label in "${AGENTS[@]}"; do
  render_plist "${SRC}/${label}.plist" "${DEST}/${label}.plist"
done

echo "Loading agents (8501 → 8787${INSTALL_GARDEN:+ → garden})..."
for label in "${AGENTS[@]}"; do
  launchctl bootstrap "${DOMAIN}" "${DEST}/${label}.plist"
  launchctl enable "${DOMAIN}/${label}"
  launchctl kickstart -k "${DOMAIN}/${label}" || true
done

sleep 4
echo
echo "Port check:"
for port in "${PORTS[@]}"; do
  if lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  :${port} listening"
  else
    echo "  :${port} NOT listening (see ${LOG_GARDEN} or ${LOG_GRID})"
  fi
done

echo
curl -sf http://127.0.0.1:8501/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('8501', d.get('served_by'), 'started', d.get('gateway_started_at'))" 2>/dev/null || echo "8501 health: FAIL"
curl -sf http://127.0.0.1:8787/ 2>/dev/null | head -c 80 && echo "" || echo "8787: check ${LOG_GARDEN}/aster8787.err.log"
echo
echo "Logs: ${LOG_GRID}/ ${LOG_GARDEN}/"
