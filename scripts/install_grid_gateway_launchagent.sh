#!/usr/bin/env bash
# Install :8501 + :8787 KeepAlive LaunchAgents (wrapper — use install_launchagents.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export INSTALL_GARDEN_STACK="${INSTALL_GARDEN_STACK:-0}"
exec bash "${ROOT}/scripts/garden/install_launchagents.sh"
