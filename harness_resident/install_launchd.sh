#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="${HOME}"
PYTHON_BIN="$(command -v python3)"
mkdir -p "$HOME_DIR/Library/LaunchAgents" "$ROOT/state/logs"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "missing $ROOT/.env — generate GRID_HARNESS_TOKEN first (package L9)"
  exit 1
fi

install_one() {
  local label="$1"
  local src="$ROOT/launchd/${label}.plist"
  local dest="$HOME_DIR/Library/LaunchAgents/${label}.plist"
  sed -e "s|__HOME__|${HOME_DIR}|g" -e "s|__PYTHON__|${PYTHON_BIN}|g" "$src" >"$dest"
  if grep -E "GRID_HARNESS_TOKEN|sk-|api_key" "$dest" >/dev/null; then
    echo "refusing to install $label: secret leaked into plist"
    rm -f "$dest"
    exit 1
  fi
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$dest"
  launchctl enable "gui/$(id -u)/$label"
  echo "Installed LaunchAgent: $label"
}

install_one com.grid.harness-api
install_one com.grid.harness-supervisor
echo "Status: launchctl print gui/$(id -u)/com.grid.harness-api"
echo "Status: launchctl print gui/$(id -u)/com.grid.harness-supervisor"
