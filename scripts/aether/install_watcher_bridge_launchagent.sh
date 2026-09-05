#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.watcher-bridge.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.watcher-bridge.plist"
LOG="${HOME}/Library/Logs/demo-aether"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.watcher-bridge"
TOKEN_FILE="${ROOT}/grid-sovereign-runtime/config/bridge_store.token"
ENV_FILE="${ROOT}/aether_watcher/.env"

mkdir -p "${LOG}"
chmod +x "${ROOT}/scripts/aether/start_watcher_bridge.sh"
# shellcheck source=ensure_venv.sh
source "${ROOT}/scripts/aether/ensure_venv.sh"
ensure_venv "${ROOT}/aether_watcher"

if [[ ! -f "${TOKEN_FILE}" ]]; then
  python3 - <<'PY' > "${TOKEN_FILE}"
import secrets
print(secrets.token_urlsafe(32))
PY
  chmod 600 "${TOKEN_FILE}"
  echo "created ${TOKEN_FILE}"
fi

BRIDGE_TOKEN="$(tr -d '\n' < "${TOKEN_FILE}")"
touch "${ENV_FILE}"
if grep -q '^BRIDGE_STORE_TOKEN=' "${ENV_FILE}" 2>/dev/null; then
  sed -i '' "s|^BRIDGE_STORE_TOKEN=.*|BRIDGE_STORE_TOKEN=${BRIDGE_TOKEN}|" "${ENV_FILE}"
else
  printf '\nBRIDGE_STORE_TOKEN=%s\n' "${BRIDGE_TOKEN}" >> "${ENV_FILE}"
fi
chmod 600 "${ENV_FILE}" 2>/dev/null || true

sed \
  -e "s|__HOME__|${HOME}|g" \
  -e "s|__DEMO_ROOT__|${ROOT}|g" \
  "${SRC}" > "${DEST}"

if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
  sleep 1
fi
launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart -k "${DOMAIN}/${LABEL}" || true
echo "watcher-bridge installed (token in bridge_store.token + aether_watcher/.env)"

PY="${ROOT}/grid-sovereign-runtime"
if [[ -f "${PY}/config/bridge_store.token" ]]; then
  export BRIDGE_STORE_TOKEN="$(tr -d '\n' < "${PY}/config/bridge_store.token")"
  launchctl kickstart -k "${DOMAIN}/com.demo.grid.gateway8501" 2>/dev/null || true
  echo "gateway8501 kickstarted with BRIDGE_STORE_TOKEN (set in start_grid_gateway.sh on next manual restart if needed)"
  sleep 2
  "${ROOT}/scripts/tailscale_serve_watchdog.sh" 2>/dev/null || true
  echo "tailscale serve watchdog run — phone 请硬刷新 grid.html 后重发"
fi
