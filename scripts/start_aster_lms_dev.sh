#!/usr/bin/env bash
# Keep demo/aster generator visible in LM Studio (lms dev must run).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN="${ROOT}/lmstudio-plugins/aster-grid-gateway"
export PATH="${HOME}/.lmstudio/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"
LMS="${HOME}/.lmstudio/bin/lms"
cd "${PLUGIN}"
exec "${LMS}" dev --no-notify
