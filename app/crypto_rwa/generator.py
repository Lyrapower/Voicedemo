"""Crypto / RWA Sovereignty pack generator — writes under outputs/crypto_rwa/."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs" / "crypto_rwa"
PACK_STATUS_PATH = OUTPUT_DIR / "crypto_rwa_pack_status.json"
INTAKE_PATH = OUTPUT_DIR / "intake.json"

PACK_FILES = {
    "rwa_infrastructure_map": "rwa_infrastructure_map.md",
    "stablecoin_evidence_card": "stablecoin_evidence_card.md",
    "agent_payment_risk_note": "agent_payment_risk_note.md",
    "rwa_proof_pack_candidate": "rwa_proof_pack_candidate.md",
}


@dataclass
class CryptoIntake:
    protocol_name: str = ""
    asset_name: str = ""
    use_case: str = ""
    focus_section: str = "stablecoins"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def load_intake() -> CryptoIntake:
    ensure_output_dir()
    if not INTAKE_PATH.exists():
        return CryptoIntake()
    try:
        data = json.loads(INTAKE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return CryptoIntake(**{k: str(data.get(k, "")) for k in CryptoIntake.__dataclass_fields__})
    except (json.JSONDecodeError, TypeError):
        pass
    return CryptoIntake()


def save_intake(intake: CryptoIntake) -> None:
    ensure_output_dir()
    INTAKE_PATH.write_text(json.dumps(asdict(intake), indent=2) + "\n", encoding="utf-8")


def _stablecoin_cards(evidence_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in evidence_cards if str(c.get("section", "")) == "stablecoins"]


def write_rwa_infrastructure_map(
    *,
    sections: list[dict[str, Any]] | None = None,
    evidence_cards: list[dict[str, Any]] | None = None,
) -> Path:
    ensure_output_dir()
    sections = sections or []
    evidence_cards = evidence_cards or []
    path = OUTPUT_DIR / PACK_FILES["rwa_infrastructure_map"]
    section_titles = [s.get("title", "") for s in sections]
    lines = [
        "# RWA Infrastructure Map",
        "",
        f"generated_at: {_utc_now()}",
        "",
        "## Stablecoin rails",
        "- [placeholder] Issuer-backed USD/EUR stablecoins",
        "- [placeholder] Redemption and attestation cadence",
        "- [open question] Reserve transparency verification path",
        "",
        "## Tokenized asset rails",
        "- [placeholder] Tokenized treasuries / credit / real estate wrappers",
        "- [placeholder] Custody and redemption chain",
        "- [open question] Counterparty and legal wrapper clarity",
        "",
        "## On-chain identity",
        "- [placeholder] Credential / attestation protocols",
        "- [open question] Financial access gating without over-collecting PII",
        "",
        "## Wallets",
        "- [placeholder] Self-custody, MPC, institutional custody patterns",
        "- [constraint] No wallet connection in this module version",
        "",
        "## Programmable payments",
        "- [placeholder] Payment intent, streaming, account abstraction experiments",
        "- [open question] Human approval gates for agent-initiated payment requests",
        "",
        "## AI-agent payment layer",
        "- [placeholder] Request / verify / settle rails with human gates",
        "- [open question] Abuse paths for autonomous payment agents",
        "",
        "## Key players / protocols (placeholder)",
        "- Circle / USDC transparency (public research only)",
        "- Tokenized treasury issuers (verify independently)",
        "- Identity / attestation standards (W3C VC, etc.)",
        "",
        "## Section registry linkage",
    ]
    for title in section_titles:
        lines.append(f"- {title}")
    if evidence_cards:
        lines.extend(["", "## Evidence cards on disk", ""])
        for card in evidence_cards[:12]:
            lines.append(f"- {card.get('id')}: {card.get('title')} ({card.get('section')})")
    lines.extend([
        "",
        "## Open questions",
        "- Which rails require 澄 review before proof-pack promotion?",
        "- Which claims lack primary-source verification?",
        "- What data is still unknown vs placeholder?",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_pack_status(last_action="rwa_infrastructure_map")
    return path


def write_stablecoin_evidence_card(
    intake: CryptoIntake | None = None,
    *,
    evidence_cards: list[dict[str, Any]] | None = None,
) -> Path:
    intake = intake or load_intake()
    evidence_cards = evidence_cards or []
    stable = _stablecoin_cards(evidence_cards)
    primary = stable[0] if stable else None
    path = OUTPUT_DIR / PACK_FILES["stablecoin_evidence_card"]
    protocol = intake.protocol_name or (primary or {}).get("title", "[placeholder protocol / asset]")
    asset = intake.asset_name or "[placeholder asset]"
    use_case = intake.use_case or "[placeholder use case — treasury, payments, settlement, etc.]"
    lines = [
        "# Stablecoin Evidence Card",
        "",
        f"generated_at: {_utc_now()}",
        "",
        "## Asset / protocol",
        f"- name: {protocol}",
        f"- asset: {asset}",
        "",
        "## Use case",
        f"- {use_case}",
        "",
        "## Issuer / backing / settlement notes",
        "- [placeholder] Issuer entity and jurisdiction",
        "- [placeholder] Reserve composition and attestation frequency",
        "- [placeholder] Redemption and settlement rails",
        *( [f"- from_evidence: {primary.get('summary', '')[:240]}" ] if primary else [] ),
        "",
        "## Risk flags",
        "- counterparty / issuer risk: [placeholder — verify]",
        "- reserve transparency risk: [placeholder — verify]",
        "- redemption / liquidity risk: [placeholder — verify]",
        "- regulatory posture: [unknown — not verified in this module]",
        "",
        "## Evidence sources (placeholder)",
        "- [placeholder] Public issuer transparency page URL",
        "- [placeholder] Attestation / audit report reference",
        *( [f"- local_evidence_file: {primary.get('file_path', '')}" ] if primary else [] ),
        "",
        "## Unknowns",
        "- Live reserve composition not verified here",
        "- No wallet or on-chain execution performed",
        "- Claims require manual validation before proof-pack use",
    ]
    if primary and primary.get("needs_cheng_review"):
        lines.extend(["", "## Review", "- needs_cheng_review: true"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_pack_status(last_action="stablecoin_evidence_card")
    return path


def write_agent_payment_risk_note() -> Path:
    path = OUTPUT_DIR / PACK_FILES["agent_payment_risk_note"]
    lines = [
        "# Agent Payment Risk Note",
        "",
        f"generated_at: {_utc_now()}",
        "",
        "## Wallet permission risks",
        "- Agent scope creep into signing or custody",
        "- Over-broad wallet permissions for automation",
        "- Missing human approval on high-value requests",
        "",
        "## Programmable payment risks",
        "- Payment intent replay or mis-routing",
        "- Streaming / subscription rails abused by agents",
        "- Weak separation between advisory and execution paths",
        "",
        "## Stablecoin flow risks",
        "- Issuer / counterparty concentration",
        "- Redemption delay during stress",
        "- Cross-rail settlement assumptions unverified",
        "",
        "## Identity / compliance risks",
        "- KYC/AML boundaries unclear for agent-mediated flows",
        "- Attestation trust without verifier independence",
        "- Cross-border exposure unknown without counsel",
        "",
        "## Automation abuse risks",
        "- Autonomous payment loops without kill switch",
        "- Prompt injection leading to payment intent changes",
        "- Missing audit log for agent payment decisions",
        "",
        "## Mitigation checklist",
        "- [ ] No wallet connection in V1 module",
        "- [ ] Human gate on any execution path",
        "- [ ] Separate research vs verified action zones",
        "- [ ] Log all agent payment recommendations",
        "- [ ] Route high-risk items to 澄 review",
        "- [ ] No investment advice or live price claims",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_pack_status(last_action="agent_payment_risk_note")
    return path


def write_rwa_proof_pack_candidate(
    *,
    evidence_cards: list[dict[str, Any]] | None = None,
) -> Path:
    evidence_cards = evidence_cards or []
    path = OUTPUT_DIR / PACK_FILES["rwa_proof_pack_candidate"]
    lines = [
        "# RWA Proof Pack Candidate",
        "",
        f"generated_at: {_utc_now()}",
        "",
        "## Scope",
        "- Research and proof layer for RWA, stablecoins, on-chain identity, wallets, programmable payments, AI-agent rails",
        "- Local files only; no wallet execution",
        "",
        "## Evidence checklist",
        "- [ ] rwa_infrastructure_map.md generated",
        "- [ ] stablecoin_evidence_card.md generated",
        "- [ ] agent_payment_risk_note.md generated",
        "- [ ] deliver/crypto/evidence/*.json cards reviewed",
        "- [ ] 澄 review queue cleared for promoted items",
        "",
        "## Data needed",
        "- Primary-source issuer / reserve disclosures",
        "- Confirmed custody and redemption paths",
        "- Identity / compliance boundary notes from qualified review",
        "",
        "## Claim to verify",
        "- \"Infrastructure map reflects current public research posture\" — not live verified",
        "- \"Stablecoin card claims are evidence-backed\" — requires manual source attach",
        "",
        "## Blockers / unknowns",
        "- No live crypto API calls in this version",
        "- Placeholder sections remain until sources attached",
        f"- evidence_cards_on_disk: {len(evidence_cards)}",
        "",
        "## Next validation action",
        "- Attach primary URLs to evidence cards",
        "- Run ./scripts/scan_crypto_rwa_public.sh for allowlisted public pages",
        "- Export Crypto/RWA pack after all sections populated",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_pack_status(last_action="rwa_proof_pack_candidate")
    return path


def export_crypto_rwa_pack(
    intake: CryptoIntake | None = None,
    *,
    sections: list[dict[str, Any]] | None = None,
    evidence_cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    intake = intake or load_intake()
    save_intake(intake)
    paths = {
        "rwa_infrastructure_map": write_rwa_infrastructure_map(sections=sections, evidence_cards=evidence_cards),
        "stablecoin_evidence_card": write_stablecoin_evidence_card(intake, evidence_cards=evidence_cards),
        "agent_payment_risk_note": write_agent_payment_risk_note(),
        "rwa_proof_pack_candidate": write_rwa_proof_pack_candidate(evidence_cards=evidence_cards),
    }
    status = update_pack_status(last_action="export_pack")
    return {"paths": {k: str(v.relative_to(ROOT)) for k, v in paths.items()}, "pack_status": status}


def read_pack_status() -> dict[str, Any]:
    ensure_output_dir()
    status: dict[str, Any] = {
        "rwa_infrastructure_map": (OUTPUT_DIR / PACK_FILES["rwa_infrastructure_map"]).exists(),
        "stablecoin_evidence_card": (OUTPUT_DIR / PACK_FILES["stablecoin_evidence_card"]).exists(),
        "agent_payment_risk_note": (OUTPUT_DIR / PACK_FILES["agent_payment_risk_note"]).exists(),
        "rwa_proof_pack_candidate": (OUTPUT_DIR / PACK_FILES["rwa_proof_pack_candidate"]).exists(),
        "last_updated": None,
        "last_action": None,
        "last_generated_file": None,
        "blocker": "NONE",
    }
    if PACK_STATUS_PATH.exists():
        try:
            saved = json.loads(PACK_STATUS_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for key in ("last_updated", "last_action", "last_generated_file", "blocker"):
                    if key in saved and saved.get(key) is not None:
                        status[key] = saved.get(key)
        except json.JSONDecodeError:
            status["blocker"] = "crypto_rwa_pack_status.json is invalid JSON"
    status["pack_complete"] = all(
        status[k]
        for k in (
            "rwa_infrastructure_map",
            "stablecoin_evidence_card",
            "agent_payment_risk_note",
            "rwa_proof_pack_candidate",
        )
    )
    if status["blocker"] is None:
        status["blocker"] = "NONE"
    return status


def update_pack_status(*, last_action: str | None = None, blocker: str | None = None) -> dict[str, Any]:
    status = read_pack_status()
    status["last_updated"] = _utc_now()
    if last_action:
        status["last_action"] = last_action
        if last_action in PACK_FILES:
            status["last_generated_file"] = f"outputs/crypto_rwa/{PACK_FILES[last_action]}"
        elif last_action == "export_pack":
            status["last_generated_file"] = "outputs/crypto_rwa/"
    if blocker is not None:
        status["blocker"] = blocker or "NONE"
    status["pack_complete"] = all(
        status[k]
        for k in (
            "rwa_infrastructure_map",
            "stablecoin_evidence_card",
            "agent_payment_risk_note",
            "rwa_proof_pack_candidate",
        )
    )
    PACK_STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status
