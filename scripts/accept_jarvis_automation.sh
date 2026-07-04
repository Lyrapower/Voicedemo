#!/usr/bin/env bash
# Jarvis automation acceptance — task registry, proof logs, platform_main API.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
REPORT="$ROOT/deliver/proof/jarvis/ACCEPTANCE_REPORT.md"
mkdir -p deliver/proof/jarvis logs/jarvis_tasks

python3 - <<'PY'
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient

root = Path(".")
report = root / "deliver/proof/jarvis/ACCEPTANCE_REPORT.md"
checks: list[tuple[str, bool, str]] = []

def add(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))

from app.platform_main import app
from app.jarvis.task_registry import list_tasks, run_task, JARVIS_ENTRY

client = TestClient(app)
add("JARVIS_ENTRY platform_main", JARVIS_ENTRY == "app.platform_main:app")
add("GET /api/jarvis/tasks 200", client.get("/api/jarvis/tasks").status_code == 200)
add("GET /api/jarvis/entry sole_entry", client.get("/api/jarvis/entry").json().get("sole_entry") is True)
tasks = list_tasks()
add("tasks registered >= 5", len(tasks) >= 5, str(len(tasks)))
ids = {t["task_id"] for t in tasks}
for tid in ("aether.snapshot.readonly", "crypto.scan.dryrun", "trading.readiness.check"):
    add(f"task {tid}", tid in ids)

r1 = run_task("aether.snapshot.readonly", dry_run=True)
add("run aether.snapshot.readonly", r1.get("ok") is True)
r2 = run_task("crypto.scan.dryrun", dry_run=True)
add("run crypto.scan.dryrun", r2.get("ok") is True)
add("proof_log exists", (root / "logs/jarvis_tasks/proof_log.jsonl").exists())
add("aether snapshot artifact", (root / "deliver/proof/jarvis/aether_snapshot_latest.json").exists())
add("merge map doc", (root / "deliver/jarvis/JARVIS_MERGE_MAP.md").exists())
add("launchd plist crypto", (root / "scripts/jarvis/launchd/com.demo.jarvis.crypto-scan-dryrun.plist").exists())
# plists must ship Disabled
plist = (root / "scripts/jarvis/launchd/com.demo.jarvis.crypto-scan-dryrun.plist").read_text()
add("launchd Disabled=true", "<key>Disabled</key>" in plist and "<true/>" in plist)

verdict = "PASS" if all(ok for _, ok, _ in checks) else "FAIL"
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
failed = [f"{a} :: {d}" for a, ok, d in checks if not ok]
lines = [
    "# Jarvis Automation Acceptance Report",
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
