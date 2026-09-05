#!/usr/bin/env bash
# Post-move: ~/Projects/demo — unified KeepAlive :8501+:8787, plugin relink, fingerprint regression.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
export INSTALL_GARDEN_STACK="${INSTALL_GARDEN_STACK:-0}"
export PYTHONPATH="${ROOT}:${ROOT}/repo${PYTHONPATH:+:${PYTHONPATH}}"

echo "=== ROOT: ${ROOT} ==="

echo "=== 1/5 LM Studio plugin → demo/aster ==="
mkdir -p "${HOME}/.lmstudio/extensions/plugins/demo"
ln -sfn "${ROOT}/lmstudio-plugins/aster-grid-gateway" "${HOME}/.lmstudio/extensions/plugins/demo/aster"
echo "OK  $(readlink "${HOME}/.lmstudio/extensions/plugins/demo/aster")"

echo "=== 2/5 LaunchAgents (all sidecars — gateway + Aether + Jarvis) ==="
bash "${ROOT}/scripts/ensure_all_sidecars.sh"

echo "=== 3/5 Port + health ==="
for port in 8501 8787; do
  lsof -iTCP:"${port}" -sTCP:LISTEN || { echo "FAIL :${port} not listening"; exit 1; }
done
curl -sf "http://127.0.0.1:8501/health" | python3 -m json.tool | head -12

echo "=== 4/5 Fingerprint regression ==="
python3 "${ROOT}/scripts/aster_tab_fingerprint_probe.py"
python3 - <<'PY'
import json
from pathlib import Path
p = Path(__import__("os").environ["ROOT"]) / "grid-sovereign-runtime/traces/proof/aster_tab_fingerprint.json"
d = json.loads(p.read_text())
gw = d.get("2b_gateway_non_stream_probe", {})
stream = d.get("2b_gateway_stream_probe", {})
ok = bool(gw.get("served_by")) and bool(stream.get("served_by_in_last_chunk"))
print("FINGERPRINT_REGRESSION", "PASS" if ok else "FAIL", "served_by=", gw.get("served_by"))
raise SystemExit(0 if ok else 1)
PY

echo "=== launchctl (KeepAlive) ==="
launchctl print "gui/$(id -u)/com.demo.grid.gateway8501" 2>/dev/null | rg "state =|path =|runs =|last exit" || true
launchctl print "gui/$(id -u)/com.demo.garden.aster8787" 2>/dev/null | rg "state =|path =|runs =|last exit" || true

echo "=== 5/5 done (ensure_all_sidecars already verified ports) ==="
