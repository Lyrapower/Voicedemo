#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REPORT="deliver/proof/crypto/ACCEPTANCE_REPORT_v0_3.md"
mkdir -p deliver/proof/crypto deliver/crypto/evidence deliver/crypto/sections

python3 - <<'PY'
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from app.platform_main import app, _collect_crypto_context

root = Path(".")
main_py = (root / "app" / "platform_main.py").read_text(encoding="utf-8", errors="ignore")
workspace = (root / "templates" / "workspace.html").read_text(encoding="utf-8", errors="ignore")
ctx = _collect_crypto_context()

checks: list[tuple[str, bool, str]] = []

def add(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))

paths = [r.path for r in app.routes if hasattr(r, "path")]
add("crypto route exists", "/ui/crypto" in paths)
add("module title", ctx.get("title") == "Crypto / RWA Sovereignty")
add("honest purpose copy", "scan_crypto_rwa_public.sh" in str(ctx.get("agent_role", "")) or "scan_crypto_rwa_public.sh" in str(ctx.get("purpose", "")))
add("scan status loaded", isinstance(ctx.get("scan_status"), dict) and ctx["scan_status"].get("source_count", 0) >= 1)
add("scan ui in template", "Optional public URL scan" in workspace and "scan_status.command" in workspace)
add("seven rwa sections loaded", len(ctx.get("rwa_sections", [])) == 7)
add("evidence cards loaded from disk", len(ctx.get("evidence_cards", [])) >= 1)
add("review queue derived from cards", isinstance(ctx.get("review_queue"), list))
add("proof candidates loaded", len(ctx.get("proof_candidates", [])) >= 1)
add("reference artifacts loaded", len(ctx.get("artifacts", [])) >= 1)
add("empty-state copy in template", "No evidence cards on disk" in workspace)
add("evidence dir shown in template", "evidence_dir" in workspace)
add("section registry paths in template", "registry_path" in workspace and "Section registry" in workspace)
add("no wallet connection boundary", "No wallet connection in V1" in main_py)

required_paths = [
    "deliver/crypto/rwa_registry.json",
    "deliver/crypto/proof_candidates.json",
    "deliver/crypto/sections/stablecoins.md",
    "deliver/crypto/sections/tokenized_rwa.md",
    "deliver/crypto/sections/onchain_identity.md",
    "deliver/crypto/sections/wallets.md",
    "deliver/crypto/sections/programmable_payments.md",
    "deliver/crypto/sections/ai_agent_rails.md",
    "deliver/crypto/sections/risk_proof.md",
    "deliver/crypto/scan_sources.json",
    "scripts/scan_crypto_rwa_public.py",
    "scripts/scan_crypto_rwa_public.sh",
    "deliver/crypto/TRUST_LAYER.md",
    "deliver/crypto/onchain/BOUNDARIES.md",
]
for rel in required_paths:
    add(f"path exists: {rel}", (root / rel).exists())

registry = json.loads((root / "deliver/crypto/rwa_registry.json").read_text(encoding="utf-8"))
add("registry schema", registry.get("schema") == "crypto_rwa_v1")
add("registry has 7 sections", len(registry.get("sections", [])) == 7)

import subprocess
dry = subprocess.run(
    [sys.executable, "scripts/scan_crypto_rwa_public.py", "--dry-run"],
    capture_output=True,
    text=True,
)
add("scan script dry-run", dry.returncode == 0, dry.stderr.strip()[:200])

verdict = "PASS" if all(ok for _, ok, _ in checks) else "FAIL"
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
report = root / "deliver/proof/crypto/ACCEPTANCE_REPORT_v0_3.md"

verified = [label for label, ok, _ in checks if ok]
failed = [f"{label}{' :: ' + detail if detail else ''}" for label, ok, detail in checks if not ok]

lines = [
    "# Crypto RWA Honest V1 Acceptance Report",
    "",
    f"generated_at: {now}",
    "module: crypto_rwa_honest_v1",
    f"verdict: {verdict}",
    "",
    "## loaded counts",
    f"- evidence_cards: {len(ctx.get('evidence_cards', []))}",
    f"- review_queue: {len(ctx.get('review_queue', []))}",
    f"- proof_candidates: {len(ctx.get('proof_candidates', []))}",
    f"- artifacts: {len(ctx.get('artifacts', []))}",
    "",
    "## verified checks",
]
lines.extend([f"- {item}" for item in verified] or ["- NONE"])
lines.extend(["", "## failed checks"])
lines.extend([f"- {item}" for item in failed] or ["- NONE"])
lines.extend([
    "",
    "FINAL VERDICT: PASS" if verdict == "PASS" else "FINAL VERDICT: FAIL",
    "",
])
report.write_text("\n".join(lines), encoding="utf-8")

raise SystemExit(0 if verdict == "PASS" else 1)
PY
