#!/usr/bin/env bash
# One-shot KeepAlive for all local sidecars (ops only — no app logic changes).
#
# Installs/reloads LaunchAgents for:
#   :8501 gateway, :8787 Aster, :8790 FIELD, lms dev
#   :8510/:8520 Aether UI + daemons
#   :8686 Jarvis (optional, default on)
#
# Usage:
#   bash scripts/ensure_all_sidecars.sh
#   INSTALL_GARDEN_STACK=1 bash scripts/ensure_all_sidecars.sh   # + :5173 :8788
#   INSTALL_JARVIS=0 bash scripts/ensure_all_sidecars.sh           # skip :8686
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
INSTALL_GARDEN_STACK="${INSTALL_GARDEN_STACK:-0}"
INSTALL_JARVIS="${INSTALL_JARVIS:-1}"

echo "=== ensure_all_sidecars ROOT=${ROOT} ==="
echo "    INSTALL_GARDEN_STACK=${INSTALL_GARDEN_STACK}  INSTALL_JARVIS=${INSTALL_JARVIS}"
echo ""

echo "=== 1/3 Grid + Aster + FIELD (:8501 :8787 :8790 lms) ==="
export INSTALL_GARDEN_STACK
bash "${ROOT}/scripts/garden/install_launchagents.sh"

echo ""
echo "=== 2/3 Aether (:8510 :8520 + daemons) ==="
bash "${ROOT}/scripts/aether/install_launchagents.sh"

if [[ "${INSTALL_JARVIS}" == "1" ]]; then
  echo ""
  echo "=== 3/3 Jarvis (:8686) ==="
  bash "${ROOT}/scripts/jarvis/install_launchagent.sh"
else
  echo ""
  echo "=== 3/3 Jarvis skipped (INSTALL_JARVIS=0) ==="
fi

FAIL=0
echo ""
echo "=== Summary ==="
check() {
  local name="$1" url="$2" expect="${3:-200}"
  local code
  code="$(curl -sf --max-time 8 -o /dev/null -w '%{http_code}' "${url}" 2>/dev/null || echo 000)"
  if [[ "${code}" == "${expect}" ]] || [[ "${expect}" == "*" && "${code}" != 000 ]]; then
    echo "  OK   ${name} ${code}"
  else
    echo "  FAIL ${name} http=${code} (${url})"
    FAIL=1
  fi
}

check ":8501 health" "http://127.0.0.1:8501/health" "*"
check ":8787 health" "http://127.0.0.1:8787/health" "*"
check ":8790 health" "http://127.0.0.1:8790/health" "*"
check ":8515 health" "http://127.0.0.1:8515/health" "*"
check ":8510 UI" "http://127.0.0.1:8510/" "200"
check ":8520 UI" "http://127.0.0.1:8520/" "200"
if [[ "${INSTALL_JARVIS}" == "1" ]]; then
  check ":8686 health" "http://127.0.0.1:8686/health" "200"
fi

python3 - <<PY || FAIL=1
import json, os, time, sys
from pathlib import Path
hb = Path(os.environ["ROOT"]) / "aether_watcher/state/heartbeat.json"
if hb.is_file():
    d = json.loads(hb.read_text())
    age = time.time() - d.get("ts", 0)
    print(f"  {'OK' if age < 120 else 'FAIL'}  watcher heartbeat {int(age)}s ago")
    sys.exit(0 if age < 120 else 1)
print("  FAIL watcher heartbeat missing")
sys.exit(1)
PY

echo ""
echo "=== 4/4 Field + Workbench stack acceptance ==="
bash "${ROOT}/scripts/verify_field_workbench_stack.sh" || FAIL=1

if [[ "${FAIL}" != "0" ]]; then
  echo ""
  echo "ENSURE_SIDECARS FAIL — logs:"
  echo "  ~/Library/Logs/demo-grid/  ~/Library/Logs/demo-garden/"
  echo "  ~/Library/Logs/demo-aether/  ~/Library/Logs/demo-jarvis/"
  exit 1
fi

echo ""
echo "ENSURE_SIDECARS PASS — KeepAlive active; survives reboot."
echo "  Gateway :8501  Workbench :8515  FIELD :8790  Aster :8787/legacy"
echo "  Aether  :8510  Watcher :8520"
[[ "${INSTALL_JARVIS}" == "1" ]] && echo "  Jarvis  :8686/ui/overview"
