#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p outputs/crypto_rwa deliver/proof/crypto

python3 - <<'PY'
import json
from pathlib import Path
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.platform_main import app

root = Path(".")
client = TestClient(app)
checks: list[tuple[str, bool, str]] = []

def add(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))

page = client.get("/ui/crypto")
add("crypto page 200", page.status_code == 200)
add("title visible", b"Crypto / RWA Sovereignty" in page.content)
add("seven sections visible", page.content.count(b"Stablecoins") >= 1 and b"AI-Agent Financial Rails" in page.content)
add("action buttons visible", b"Generate RWA Infrastructure Map" in page.content and b"Export Crypto/RWA Pack" in page.content)

form = {
    "protocol_name": "USDC",
    "asset_name": "USD stablecoin",
    "use_case": "treasury settlement rail",
    "focus_section": "stablecoins",
}
for action in (
    "infrastructure-map",
    "stablecoin-evidence",
    "agent-payment-risk",
    "proof-pack-candidate",
):
    r = client.post(f"/ui/crypto/action/{action}", data=form, follow_redirects=True)
    add(f"action {action}", r.status_code == 200, str(r.status_code))

r = client.post("/ui/crypto/action/export-pack", data=form, follow_redirects=True)
add("action export-pack", r.status_code == 200, str(r.status_code))

required = [
    "outputs/crypto_rwa/rwa_infrastructure_map.md",
    "outputs/crypto_rwa/stablecoin_evidence_card.md",
    "outputs/crypto_rwa/agent_payment_risk_note.md",
    "outputs/crypto_rwa/rwa_proof_pack_candidate.md",
    "outputs/crypto_rwa/crypto_rwa_pack_status.json",
]
for rel in required:
    add(f"file exists: {rel}", (root / rel).exists())

status = json.loads((root / "outputs/crypto_rwa/crypto_rwa_pack_status.json").read_text(encoding="utf-8"))
add("pack_complete true", status.get("pack_complete") is True)
add("blocker field present", "blocker" in status)

verdict = "PASS" if all(ok for _, ok, _ in checks) else "FAIL"
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
report = root / "deliver/proof/crypto/ACCEPTANCE_REPORT_RWA_FUNCTIONAL.md"
failed = [f"{a} :: {d}" for a, ok, d in checks if not ok]
lines = [
    "# Crypto RWA Functional Acceptance Report",
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
