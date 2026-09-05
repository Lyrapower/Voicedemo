#!/usr/bin/env bash
# Deploy aster-field from ~/Projects/demo/aster-field (zip extract + build + :8790 LaunchAgent).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIELD="${ROOT}/aster-field"
ZIP="${1:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/Downloads/aster-field.zip}"

if [[ ! -d "${FIELD}/backend" ]]; then
  [[ -f "${ZIP}" ]] || { echo "missing ${ZIP} and ${FIELD}"; exit 1; }
  unzip -qo "${ZIP}" -d "${ROOT}"
fi

ARCH=$(uname -m); case "$ARCH" in arm64) NODE_ARCH=arm64;; *) NODE_ARCH=x64;; esac
NODE_VER=v22.22.0
NODE_DIR="/tmp/node-${NODE_VER}-darwin-${NODE_ARCH}"
if [[ ! -x "${NODE_DIR}/bin/npm" ]]; then
  curl -fsSL "https://nodejs.org/dist/${NODE_VER}/node-${NODE_VER}-darwin-${NODE_ARCH}.tar.gz" | tar -xz -C /tmp
fi
export PATH="${NODE_DIR}/bin:$PATH"

cd "${FIELD}/frontend"
npm install
npm run build

python3 -m pip install -q -r "${FIELD}/backend/requirements.txt" pytest
cd "${FIELD}" && python3 -m pytest tests/ -q

bash "${ROOT}/scripts/install_aster_field_launchagent.sh"
launchctl kickstart -k "gui/$(id -u)/com.demo.garden.aster8787" || true
sleep 3
bash "${ROOT}/scripts/verify_aster_field_v1.sh"

echo ""
echo "ASTER FIELD ready:"
echo "  UI:     http://127.0.0.1:8790/"
echo "  Entry:  http://127.0.0.1:8787/ → redirects to FIELD"
echo "  Legacy: http://127.0.0.1:8787/legacy/"
