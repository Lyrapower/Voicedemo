#!/usr/bin/env bash
# ASTER FIELD :8790 — launchd entry (read-only bridge + static UI). No port kill.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIELD="${ROOT}/aster-field"
PORT=8790

if lsof -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: :${PORT} already in use — use launchctl kickstart, do not kill from scripts." >&2
  echo "  launchctl kickstart -k \"gui/\$(id -u)/com.demo.field.bridge8790\"" >&2
  exit 1
fi

cd "${FIELD}"
if [[ ! -d frontend/dist ]]; then
  echo "WARN: frontend/dist missing — run: cd aster-field/frontend && npm ci && npm run build" >&2
fi
python3 -m pip install -q -r backend/requirements.txt
exec python3 -m backend.app
