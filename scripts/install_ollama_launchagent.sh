#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/scripts/launchd/com.demo.grid.ollama11434.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.grid.ollama11434.plist"
LOG_DIR="${HOME}/Library/Logs/demo-grid"

mkdir -p "${LOG_DIR}"
sed -e "s|__HOME__|${HOME}|g" -e "s|__DEMO_ROOT__|${ROOT}|g" "${SRC}" >"${DEST}"
launchctl bootout "gui/$(id -u)/com.demo.grid.ollama11434" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${DEST}"
launchctl enable "gui/$(id -u)/com.demo.grid.ollama11434"
launchctl kickstart -k "gui/$(id -u)/com.demo.grid.ollama11434" || true
echo "Installed ${DEST}"
echo "Requires Ollama app — run: bash ${ROOT}/scripts/install_ollama_coder.sh"
