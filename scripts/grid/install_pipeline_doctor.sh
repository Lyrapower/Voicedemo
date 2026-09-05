#!/usr/bin/env bash
# Install pipeline_doctor launchd + sync iCloud Downloads launcher.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$REPO/scripts/grid/pipeline_doctor.py"
PLIST_SRC="$REPO/scripts/grid/launchd/com.grid.pipeline-doctor.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.grid.pipeline-doctor.plist"
ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Downloads/pipeline doctor.py"
ENV_FILE="$REPO/scripts/grid/pipeline_doctor.env"

chmod +x "$SRC"
chmod +x "$0"

BARK=""
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  BARK="${DOCTOR_BARK_URL:-}"
fi

python3 <<PY
from pathlib import Path
import plistlib
src = Path("$PLIST_SRC")
dest = Path("$PLIST_DEST")
data = plistlib.loads(src.read_bytes())
env = data.setdefault("EnvironmentVariables", {})
env["DOCTOR_BARK_URL"] = "$BARK"
dest.write_bytes(plistlib.dumps(data))
PY

launchctl bootout "gui/$(id -u)/com.grid.pipeline-doctor" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"

cat >"$ICLOUD" <<EOF
#!/usr/bin/env python3
"""Launcher — canonical: $SRC"""
import runpy
import sys
CANONICAL = "$SRC"
sys.argv[0] = CANONICAL
try:
    runpy.run_path(CANONICAL, run_name="__main__")
except SystemExit as exc:
    raise SystemExit(exc.code) from None
EOF
chmod +x "$ICLOUD"

echo "OK — pipeline_doctor installed"
echo "  canonical: $SRC"
echo "  iCloud:      $ICLOUD"
echo "  launchd:     com.grid.pipeline-doctor @ 06:40 weekdays (before poolscan 06:45)"
echo "  log:         /tmp/grid_pipeline_doctor.log"
echo "  bark:        ${BARK:-未配置 — 填 scripts/grid/pipeline_doctor.env 后重装}"
echo ""
export DOCTOR_BARK_URL="$BARK"
DOCTOR_BARK_URL="$BARK" "$SRC"
