"""Local AI Nodes pack generator — writes files under outputs/local_ai_node/."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs" / "local_ai_node"
INTAKE_PATH = OUTPUT_DIR / "intake.json"
PACK_STATUS_PATH = OUTPUT_DIR / "pack_status.json"

PACK_FILES = {
    "pilot_brief": "pilot_brief.md",
    "package_recommendation": "package_recommendation.json",
    "delivery_checklist": "delivery_checklist.md",
    "delivery_timeline": "delivery_timeline.md",
    "agent_roles": "agent_roles.md",
}

TIERS = {
    "Lite Node": {
        "price_range": "$1,800–$2,500",
        "target": "solo creator / AI beginner / privacy-aware user",
        "includes": [
            "local model setup",
            "model SSD or model folder setup",
            "1–2 local models",
            "basic launcher",
            "simple usage guide",
        ],
    },
    "Pro Node": {
        "price_range": "$3,500–$5,000",
        "target": "AI-heavy founder / researcher / consultant",
        "includes": [
            "local model",
            "OCR → Markdown",
            "Obsidian/RAG",
            "FastAPI/local router",
            "30-day support",
            "setup guide",
        ],
    },
    "Sovereign Node": {
        "price_range": "$7,000+",
        "target": "high-privacy operator / small team / advanced creator",
        "includes": [
            "workstation planning",
            "local model deployment",
            "private knowledge base",
            "AICG/field engine support",
            "maintenance plan",
            "optional GPU node planning",
        ],
    },
}

BEST_FIT = [
    "AI-heavy solo founders",
    "high-end creators / AICG small teams",
    "consultants with private client data",
    "researchers / writers with private notes",
    "operators who need local AI but do not want to deploy it themselves",
]

NOT_TARGET = [
    "local model hobbyists",
    "people asking for free tutorials",
    "open-source-only users",
    "cheap SSD buyers",
    "engineers who prefer DIY everything",
]


@dataclass
class Intake:
    customer_type: str = ""
    current_device: str = ""
    target_use_case: str = ""
    privacy_sensitivity: str = ""
    desired_local_functions: str = ""
    budget_range: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def load_intake() -> Intake:
    ensure_output_dir()
    if not INTAKE_PATH.exists():
        return Intake()
    try:
        data = json.loads(INTAKE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return Intake(**{k: str(data.get(k, "")) for k in Intake.__dataclass_fields__})
    except (json.JSONDecodeError, TypeError):
        pass
    return Intake()


def save_intake(intake: Intake) -> None:
    ensure_output_dir()
    INTAKE_PATH.write_text(json.dumps(intake.to_dict(), indent=2) + "\n", encoding="utf-8")


def _parse_budget_upper(budget: str) -> int | None:
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", budget)]
    if not nums:
        return None
    return max(nums)


def recommend_tier(intake: Intake) -> str:
    budget_upper = _parse_budget_upper(intake.budget_range)
    privacy = intake.privacy_sensitivity.lower()
    functions = intake.desired_local_functions.lower()
    use_case = intake.target_use_case.lower()

    if budget_upper is not None:
        if budget_upper < 3000:
            return "Lite Node"
        if budget_upper < 6500:
            return "Pro Node"
        return "Sovereign Node"

    if any(k in privacy for k in ("high", "strict", "sovereign", "regulated")):
        return "Sovereign Node"
    if any(k in functions for k in ("rag", "ocr", "obsidian", "fastapi", "router")):
        return "Pro Node"
    if any(k in use_case for k in ("team", "workstation", "gpu", "maintenance")):
        return "Sovereign Node"
    return "Pro Node"


def _review_flags(intake: Intake, tier: str) -> dict[str, bool]:
    text = " ".join(intake.to_dict().values()).lower()
    cheng = any(
        k in text
        for k in (
            "hipaa",
            "regulated",
            "legal",
            "compliance",
            "security audit",
            "high privacy",
            "strict privacy",
            "sovereign",
        )
    )
    lyra = tier == "Sovereign Node" or "tbd" in intake.budget_range.lower() or not intake.budget_range.strip()
    return {"needs_cheng_review": cheng, "needs_lyra_review": lyra}


def write_pilot_brief(intake: Intake) -> Path:
    ensure_output_dir()
    tier = recommend_tier(intake)
    flags = _review_flags(intake, tier)
    path = OUTPUT_DIR / PACK_FILES["pilot_brief"]
    lines = [
        "# Pilot Brief — Private Local AI Node",
        "",
        f"generated_at: {_utc_now()}",
        "",
        "## Customer intake",
        f"- customer_type: {intake.customer_type or 'unspecified'}",
        f"- current_device: {intake.current_device or 'unspecified'}",
        f"- target_use_case: {intake.target_use_case or 'unspecified'}",
        f"- privacy_sensitivity: {intake.privacy_sensitivity or 'unspecified'}",
        f"- desired_local_functions: {intake.desired_local_functions or 'unspecified'}",
        f"- budget_range: {intake.budget_range or 'unspecified'}",
        "",
        "## Customer-fit assessment",
        f"- preliminary_tier: {tier}",
        f"- fit_signal: {'strong' if intake.customer_type and intake.target_use_case else 'needs_more_intake'}",
        "",
        "## Pipeline",
        "OCR → Markdown → Obsidian/RAG → Local Qwen → FastAPI/local router → iPhone/iPad/Mac access",
        "",
        "## Review routing",
        f"- needs_cheng_review: {str(flags['needs_cheng_review']).lower()}",
        f"- needs_lyra_review: {str(flags['needs_lyra_review']).lower()}",
        "",
        "## Constraints",
        "- No payment processing in module",
        "- No hardware purchase automation",
        "- No external API calls from generator",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_pack_status(last_action="pilot_brief")
    return path


def write_package_recommendation(intake: Intake | None = None) -> Path:
    intake = intake or load_intake()
    ensure_output_dir()
    tier = recommend_tier(intake)
    tier_data = TIERS[tier]
    flags = _review_flags(intake, tier)
    doc = {
        "generated_at": _utc_now(),
        "recommended_tier": tier,
        "price_range": tier_data["price_range"],
        "target": tier_data["target"],
        "includes": tier_data["includes"],
        "alternatives": {
            "Lite Node": TIERS["Lite Node"]["price_range"],
            "Pro Node": TIERS["Pro Node"]["price_range"],
            "Sovereign Node": TIERS["Sovereign Node"]["price_range"],
        },
        "intake_summary": intake.to_dict(),
        "review_routing": flags,
        "rationale": _recommendation_rationale(intake, tier),
    }
    path = OUTPUT_DIR / PACK_FILES["package_recommendation"]
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    update_pack_status(last_action="package_recommendation")
    return path


def _recommendation_rationale(intake: Intake, tier: str) -> str:
    parts = [f"Selected {tier} based on intake."]
    if intake.budget_range:
        parts.append(f"Budget signal: {intake.budget_range}.")
    if intake.privacy_sensitivity:
        parts.append(f"Privacy signal: {intake.privacy_sensitivity}.")
    if intake.desired_local_functions:
        parts.append(f"Requested functions: {intake.desired_local_functions}.")
    return " ".join(parts)


def write_delivery_checklist(intake: Intake | None = None) -> Path:
    intake = intake or load_intake()
    tier = recommend_tier(intake)
    path = OUTPUT_DIR / PACK_FILES["delivery_checklist"]
    lines = [
        "# Delivery Checklist",
        "",
        f"generated_at: {_utc_now()}",
        f"package_tier: {tier}",
        "",
        "## Setup steps",
        "- Confirm hardware baseline and storage for models",
        "- Install local model runtime (Qwen) and verify inference",
        "- Configure OCR → Markdown pipeline",
        "- Wire Obsidian/RAG vault paths",
        "- Stand up FastAPI/local router on LAN-only bind",
        "- Pair iPhone/iPad/Mac client access with auth boundary",
        "- Run smoke tests and capture proof artifacts",
        "",
        "## Hardware requirements",
        "- Mac with sufficient RAM for chosen tier",
        "- SSD for model weights (size depends on tier)",
        "- Stable LAN for device access",
        *(["- Optional dedicated GPU/workstation planning (Sovereign)"] if tier == "Sovereign Node" else []),
        "",
        "## Software requirements",
        "- Local Qwen model bundle",
        "- OCR toolchain",
        "- Obsidian or compatible markdown/RAG stack",
        "- FastAPI local router",
        "- Launcher scripts and usage guide",
        "",
        "## Data migration checklist",
        "- Inventory source documents for OCR",
        "- Define markdown folder structure",
        "- Map RAG index boundaries",
        "- Verify no customer PII leaves local disk during pilot",
        "",
        "## Support checklist",
        *(["- Deliver setup guide", "- 30-day support window (Pro/Sovereign)"] if tier != "Lite Node" else ["- Basic setup guide handoff (Lite)"]),
        "- Escalate privacy/security questions to 澄 review",
        "- Escalate pricing/package ambiguity to Lyra review",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_pack_status(last_action="delivery_checklist")
    return path


def write_delivery_timeline(intake: Intake | None = None) -> Path:
    intake = intake or load_intake()
    tier = recommend_tier(intake)
    path = OUTPUT_DIR / PACK_FILES["delivery_timeline"]
    lines = [
        "# 4-Week Delivery Timeline",
        "",
        f"generated_at: {_utc_now()}",
        f"package_tier: {tier}",
        "",
        "## Week 1 — Intake & baseline",
        "- Finalize pilot brief and customer-fit assessment",
        "- Confirm hardware/software baseline",
        "- Lock privacy boundary and review flags",
        "",
        "## Week 2 — Core local stack",
        "- Deploy local Qwen models",
        "- Stand up OCR → Markdown pipeline",
        "- Initialize Obsidian/RAG structure",
        "",
        "## Week 3 — Router & device access",
        "- Configure FastAPI/local router",
        "- Enable iPhone/iPad/Mac access pattern",
        "- Run integration smoke tests",
        "",
        "## Week 4 — Handoff & support",
        "- Deliver guides and checklists",
        "- Capture proof artifacts under outputs/local_ai_node/",
        "- Open support window per package tier",
        "- Route open security/pricing questions to 澄 / Lyra",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_pack_status(last_action="delivery_timeline")
    return path


def write_agent_roles(intake: Intake | None = None) -> Path:
    intake = intake or load_intake()
    flags = _review_flags(intake, recommend_tier(intake))
    path = OUTPUT_DIR / PACK_FILES["agent_roles"]
    lines = [
        "# Agent Roles Plan",
        "",
        f"generated_at: {_utc_now()}",
        "",
        "## Qwen (local)",
        "- Run on-device inference for private workflows",
        "- Never exfiltrate customer documents",
        "",
        "## Cursor",
        "- Execute implementation tasks against local repo",
        "- Generate and update delivery artifacts",
        "",
        "## GPT/Claude API (sanitized review)",
        "- Optional external review on redacted summaries only",
        "- Disabled by default in V1 module actions",
        "",
        "## 澄 (audit)",
        "- Review privacy/security flags",
        f"- Triggered: {flags['needs_cheng_review']}",
        "",
        "## Lyra (authority)",
        "- Resolve product/pricing ambiguity",
        f"- Triggered: {flags['needs_lyra_review']}",
        "",
        "## Module bans",
        "- No payment connection",
        "- No hardware purchase",
        "- No fake compatibility promises",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_pack_status(last_action="agent_roles")
    return path


def export_full_pack(intake: Intake | None = None) -> dict[str, Any]:
    intake = intake or load_intake()
    save_intake(intake)
    paths = {
        "pilot_brief": write_pilot_brief(intake),
        "package_recommendation": write_package_recommendation(intake),
        "delivery_checklist": write_delivery_checklist(intake),
        "delivery_timeline": write_delivery_timeline(intake),
        "agent_roles": write_agent_roles(intake),
    }
    status = update_pack_status(last_action="export_pack")
    return {"paths": {k: str(v.relative_to(ROOT)) for k, v in paths.items()}, "pack_status": status}


def read_pack_status() -> dict[str, Any]:
    ensure_output_dir()
    status: dict[str, Any] = {
        "pilot_brief": (OUTPUT_DIR / PACK_FILES["pilot_brief"]).exists(),
        "package_recommendation": (OUTPUT_DIR / PACK_FILES["package_recommendation"]).exists(),
        "delivery_checklist": (OUTPUT_DIR / PACK_FILES["delivery_checklist"]).exists(),
        "delivery_timeline": (OUTPUT_DIR / PACK_FILES["delivery_timeline"]).exists(),
        "agent_roles": (OUTPUT_DIR / PACK_FILES["agent_roles"]).exists(),
        "last_updated": None,
        "last_action": None,
        "last_generated_file": None,
        "blocker": None,
    }
    if PACK_STATUS_PATH.exists():
        try:
            saved = json.loads(PACK_STATUS_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for key in ("last_updated", "last_action", "last_generated_file", "blocker"):
                    if key in saved:
                        status[key] = saved.get(key)
        except json.JSONDecodeError:
            status["blocker"] = "pack_status.json is invalid JSON"
    status["pack_complete"] = all(
        status[k] for k in ("pilot_brief", "package_recommendation", "delivery_checklist", "delivery_timeline", "agent_roles")
    )
    return status


def update_pack_status(*, last_action: str | None = None, blocker: str | None = None) -> dict[str, Any]:
    status = read_pack_status()
    status["last_updated"] = _utc_now()
    if last_action:
        status["last_action"] = last_action
        key_to_file = {k: PACK_FILES[k] for k in PACK_FILES}
        if last_action in key_to_file:
            status["last_generated_file"] = f"outputs/local_ai_node/{key_to_file[last_action]}"
        elif last_action == "export_pack":
            status["last_generated_file"] = "outputs/local_ai_node/"
    status["blocker"] = blocker
    status["pack_complete"] = all(
        status[k] for k in ("pilot_brief", "package_recommendation", "delivery_checklist", "delivery_timeline", "agent_roles")
    )
    PACK_STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status
