#!/usr/bin/env bash
# GRID Workbench UI (:8515) — launchd entry; static HTML only (APIs on :8501).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GS="$ROOT/grid-sovereign-runtime"
PORT=8515

if lsof -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: :${PORT} already in use — use launchctl kickstart, do not kill from scripts." >&2
  echo "  launchctl kickstart -k \"gui/\$(id -u)/com.demo.workbench.ui8515\"" >&2
  exit 1
fi

cd "$GS"
echo "GRID Workbench sidecar → http://127.0.0.1:${PORT}"
echo "  b11:        /grid_workbench_b11.html"
echo "  multimodal: /grid_multimodal.html"
echo "  Kimi:       POST /task/candidate"
echo "  EXPANDED:   POST /task/expanded"
echo "  Chat/final still uses Grid :8501 /v1/chat/completions"
exec python3 workbench/workbench_app.py
