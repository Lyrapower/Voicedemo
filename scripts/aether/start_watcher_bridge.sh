#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="${ROOT}/aether_watcher"
cd "${APP}"
# shellcheck source=ensure_venv.sh
source "$(dirname "$0")/ensure_venv.sh"
ensure_venv "${APP}"
if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi
exec "${APP}/.venv/bin/python" watcher_bridge.py
