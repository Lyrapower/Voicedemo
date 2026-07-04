#!/usr/bin/env bash
# Aether Watcher V0.2 acceptance — starts daemon + dashboard if needed, verifies state artifacts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
AW="$ROOT/aether_watcher"
REPORT="$ROOT/deliver/proof/aether_watcher/ACCEPTANCE_REPORT.md"
PORT="${WATCHER_DASHBOARD_PORT:-8520}"
mkdir -p deliver/proof/aether_watcher logs

DAEMON_STARTED=0
DASH_STARTED=0
cleanup() {
  if [ "$DASH_STARTED" -eq 1 ] && [ -n "${DASH_PID:-}" ]; then kill "$DASH_PID" 2>/dev/null || true; fi
  if [ "$DAEMON_STARTED" -eq 1 ] && [ -n "${DAEMON_PID:-}" ]; then kill "$DAEMON_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT

# venv
if [ ! -d "$AW/.venv" ]; then
  python3 -m venv "$AW/.venv"
  "$AW/.venv/bin/pip" install -q -r "$AW/requirements.txt"
fi

# start daemon if no fresh heartbeat
if [ ! -f "$AW/state/heartbeat.json" ] || ! python3 - <<PY
import json, time, sys
from pathlib import Path
hb = json.loads(Path("$AW/state/heartbeat.json").read_text())
sys.exit(0 if time.time() - hb.get("ts", 0) < 120 else 1)
PY
then
  WATCHER_QUIET=1 nohup "$AW/.venv/bin/python" "$AW/aether_watcher.py" >"$AW/state/accept_daemon.log" 2>&1 &
  DAEMON_PID=$!
  DAEMON_STARTED=1
  for i in $(seq 1 30); do
    [ -f "$AW/state/heartbeat.json" ] && break
    sleep 1
  done
fi

# start dashboard if port free
if ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  nohup "$AW/.venv/bin/streamlit" run "$AW/watcher_dashboard.py" \
    --server.address 127.0.0.1 --server.port "$PORT" \
    --browser.gatherUsageStats false >"$AW/state/accept_dashboard.log" 2>&1 &
  DASH_PID=$!
  DASH_STARTED=1
  for i in $(seq 1 45); do
    curl -sf "http://127.0.0.1:${PORT}/_stcore/health" >/dev/null 2>&1 && break
    sleep 1
  done
fi

python3 - <<'PY'
import json
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

root = Path(".")
aw = root / "aether_watcher"
report = root / "deliver/proof/aether_watcher/ACCEPTANCE_REPORT.md"
checks: list[tuple[str, bool, str]] = []

def add(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))

# --- source files (Downloads integration cross-check) ---
required_files = [
    "aether_watcher/aether_watcher.py",
    "aether_watcher/watcher_dashboard.py",
    "aether_watcher/watch_targets.toml",
    "aether_watcher/.env.example",
    "aether_watcher/run_watcher.sh",
    "aether_watcher/run_dashboard.sh",
    "aether_watcher/README.md",
    "deliver/aether_watcher/INTEGRATION_LOG.md",
    "docs/aether_watcher/aether_watcher.pdf",
]
for rel in required_files:
    add(f"file: {rel}", (root / rel).exists())

# --- toml: V0.2 targets present ---
cfg = tomllib.loads((aw / "watch_targets.toml").read_text(encoding="utf-8"))
names = {t["name"] for t in cfg.get("targets", [])}
add("target OptionScanner (scanner_health)", "OptionScanner" in names)
add("target BTC-USD (price)", "BTC-USD" in names)
add("target AnthropicNews (rss)", "AnthropicNews" in names)
opt = next(t for t in cfg["targets"] if t["name"] == "OptionScanner")
add("OptionScanner points at aether_nexus", "aether_nexus" in opt.get("scanner_dir", ""))
add("signals_file dryrun_state/signals.json", opt.get("signals_file") == "dryrun_state/signals.json")

# --- runtime state ---
hb_path = aw / "state/heartbeat.json"
add("heartbeat.json exists", hb_path.exists())
if hb_path.exists():
    hb = json.loads(hb_path.read_text(encoding="utf-8"))
    age = time.time() - hb.get("ts", 0)
    add("heartbeat fresh (<120s)", age < 120, f"age={int(age)}s")
    add("heartbeat lists targets", len(hb.get("targets", [])) >= 1, str(len(hb.get("targets", []))))
    types = {t.get("type") for t in hb.get("targets", [])}
    add("scanner_health in heartbeat", "scanner_health" in types)

add("watch_state.json exists", (aw / "state/watch_state.json").exists())
add("events.json exists", (aw / "state/events.json").exists())
add("watcher.log exists", (aw / "state/watcher.log").exists())

# --- dashboard localhost only ---
port = int(__import__("os").environ.get("WATCHER_DASHBOARD_PORT", "8520"))
dash = subprocess.run(["curl", "-sf", f"http://127.0.0.1:{port}/_stcore/health"], capture_output=True)
add("dashboard health :8520", dash.returncode == 0, dash.stderr.decode()[:120])

# --- module import + one-shot scanner check ---
spec = __import__("importlib.util").util.spec_from_file_location("aw", aw / "aether_watcher.py")
mod = __import__("importlib.util").util.module_from_spec(spec)
spec.loader.exec_module(mod)
t = next(x for x in cfg["targets"] if x["name"] == "OptionScanner")
st = mod.check_scanner_health(t, {})
add("OptionScanner check runs", "last_check" in st)
add("log_silence_min recorded", "log_silence_min" in st, str(st.get("log_silence_min")))

verdict = "PASS" if all(ok for _, ok, _ in checks) else "FAIL"
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
failed = [f"{a} :: {d}" for a, ok, d in checks if not ok]
lines = [
    "# Aether Watcher V0.2 Acceptance Report",
    "",
    f"generated_at: {now}",
    f"verdict: {verdict}",
    "",
    "## checks",
]
for label, ok, detail in checks:
    mark = "PASS" if ok else "FAIL"
    lines.append(f"- {mark} - {label}" + (f" ({detail})" if detail and not ok else ""))
failed_lines = [f"- {x}" for x in failed] or ["- NONE"]
lines.extend(["", "## failed", *failed_lines, "", f"FINAL VERDICT: {verdict}", ""])
report.write_text("\n".join(lines), encoding="utf-8")
print(verdict)
print(report)
sys.exit(0 if verdict == "PASS" else 1)
PY
