#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p outputs/local_ai_node deliver/proof/local_ai_nodes

python3 - <<'PY'
import json
from pathlib import Path
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import app

root = Path(".")
checks: list[tuple[str, bool, str]] = []

def add(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))

client = TestClient(app)
overview = client.get("/ui/overview")
add("overview 200", overview.status_code == 200)
add("trading removed from main cards", b"Private Local AI Nodes" in overview.content and b'"Trading"' not in overview.content.split(b"jv-module-grid")[1][:4000] if b"jv-module-grid" in overview.content else b"Trading" not in overview.content[:8000])
add("local ai nodes page 200", client.get("/ui/local-ai-nodes").status_code == 200)
add("aether nexus bridge page", client.get("/ui/trading").status_code == 200 and b"Aether Nexus" in client.get("/ui/trading").content)

form = {
    "customer_type": "AI-heavy solo founder",
    "current_device": "MacBook Pro M3, 36GB RAM",
    "target_use_case": "Private client research notes + OCR pipeline",
    "privacy_sensitivity": "high privacy",
    "desired_local_functions": "OCR, Obsidian RAG, local Qwen, FastAPI router",
    "budget_range": "$4,000-$5,000",
}

for action in (
    "pilot-brief",
    "package-recommendation",
    "delivery-checklist",
    "delivery-timeline",
    "agent-roles",
):
    r = client.post(f"/ui/local-ai-nodes/action/{action}", data=form, follow_redirects=True)
    add(f"action {action}", r.status_code == 200, str(r.status_code))

r = client.post("/ui/local-ai-nodes/action/export-pack", data=form, follow_redirects=True)
add("action export-pack", r.status_code == 200, str(r.status_code))

required = [
    "outputs/local_ai_node/pilot_brief.md",
    "outputs/local_ai_node/package_recommendation.json",
    "outputs/local_ai_node/delivery_checklist.md",
    "outputs/local_ai_node/delivery_timeline.md",
    "outputs/local_ai_node/agent_roles.md",
    "outputs/local_ai_node/pack_status.json",
]
for rel in required:
    add(f"file exists: {rel}", (root / rel).exists())

status = json.loads((root / "outputs/local_ai_node/pack_status.json").read_text(encoding="utf-8"))
add("pack_status pack_complete", status.get("pack_complete") is True)
add("generator script exists", (root / "scripts/accept_local_ai_nodes.sh").exists())

verdict = "PASS" if all(ok for _, ok, _ in checks) else "FAIL"
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
report = root / "deliver/proof/local_ai_nodes/ACCEPTANCE_REPORT.md"
failed = [f"{a} :: {d}" for a, ok, d in checks if not ok]
lines = [
    "# Private Local AI Nodes Acceptance Report",
    "",
    f"generated_at: {now}",
    f"verdict: {verdict}",
    "",
    "## failed checks",
]
lines.extend([f"- {x}" for x in failed] or ["- NONE"])
lines.extend(["", f"FINAL VERDICT: {verdict}", ""])
report.write_text("\n".join(lines), encoding="utf-8")
raise SystemExit(0 if verdict == "PASS" else 1)
PY
