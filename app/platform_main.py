import time
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import os

from models.llama_loader import GridOllamaClient
from compiler.semantic_mapper import SemanticMapper
from logs.grid_logger import log_grid_event
from state.grid_state import read_state, write_state
from app.crypto_rwa.generator import (
    OUTPUT_DIR as CRYPTO_RWA_OUTPUT_DIR,
    CryptoIntake,
    export_crypto_rwa_pack,
    load_intake as load_crypto_intake,
    read_pack_status as read_crypto_rwa_pack_status,
    save_intake as save_crypto_intake,
    write_agent_payment_risk_note,
    write_rwa_infrastructure_map,
    write_rwa_proof_pack_candidate,
    write_stablecoin_evidence_card,
)
from app.local_ai_nodes.generator import (
    BEST_FIT,
    NOT_TARGET,
    OUTPUT_DIR,
    TIERS,
    Intake,
    export_full_pack,
    load_intake,
    read_pack_status,
    save_intake,
    write_agent_roles,
    write_delivery_checklist,
    write_delivery_timeline,
    write_package_recommendation,
    write_pilot_brief,
)
from app.router.compiled_memory import build_compiled_memory, load_compiled_context
from app.router.review_pipeline import ReviewPipeline
AETHER_NEXUS_HOST = os.environ.get("AETHER_NEXUS_HOST", "127.0.0.1")
AETHER_NEXUS_PORT = int(os.environ.get("AETHER_NEXUS_PORT", "8510"))
AETHER_NEXUS_URL = f"http://{AETHER_NEXUS_HOST}:{AETHER_NEXUS_PORT}"

try:
    from app.router.bridge_api import router as bridge_router  # type: ignore
except Exception:
    bridge_router = None  # type: ignore

try:
    from app.router.round_api import router as round_router  # type: ignore
except Exception:
    round_router = None  # type: ignore

try:
    from app.jarvis.router import router as jarvis_router  # type: ignore
    from app.jarvis.aether_readonly_adapter import load_aether_snapshot
    from app.jarvis.task_registry import JARVIS_ENTRY, JARVIS_HOST, JARVIS_PORT, list_tasks
    from app.jarvis.proof_log import tail_proof_log
except Exception:
    jarvis_router = None  # type: ignore
    load_aether_snapshot = None  # type: ignore
    list_tasks = None  # type: ignore
    tail_proof_log = None  # type: ignore
    JARVIS_ENTRY = "app.platform_main:app"
    JARVIS_HOST = "127.0.0.1"
    JARVIS_PORT = 8686

ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(ROOT / "templates"))
DELIVER_DIR = ROOT / "deliver"
LOGS_DIR = ROOT / "logs"
CLIENT_DIR = ROOT / "clients" / "openclaw_senior_flutter"


app = FastAPI(title="Aster-Grid Interface", version="1.0")
# Architecture lock: no POST /route unified chain on Grid. Primary: /health, /map_intent, /transmit.
# Mount static first so /static/* is never shadowed by routers and url_for("static") resolves.
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
try:
    if bridge_router is not None:
        app.include_router(bridge_router)
except Exception:
    pass
try:
    if round_router is not None:
        app.include_router(round_router)
except Exception:
    pass
try:
    if jarvis_router is not None:
        app.include_router(jarvis_router)
except Exception:
    pass
ollama = GridOllamaClient(model=os.environ.get("OLLAMA_MODEL", "qwen3:8b"))
mapper = SemanticMapper()


@dataclass
class RoundBlock:
    owner: str
    status: str
    title: str
    body: str
    artifact_path: str = ""


@dataclass
class HandoffRecord:
    from_role: str
    to_role: str
    status: str
    artifact_path: str
    summary: str
    display_line: str = ""


@dataclass
class CollaborationRound:
    round_id: str
    status: str
    owner: str
    input_block: RoundBlock
    audit_block: RoundBlock
    compile_pack_block: RoundBlock
    decision_block: RoundBlock
    execution_result: RoundBlock
    proof_link: str
    handoffs: list[HandoffRecord] = field(default_factory=list)


@app.on_event("startup")
async def startup_event() -> None:
    build_compiled_memory()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await ollama.close()


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    pipeline = ReviewPipeline()
    payload: Dict[str, Any] = {
        "status": "ok",
        "service": "jarvis_routing",
        "external_enabled": pipeline._is_external_enabled(),
        "adapters_initialized": pipeline.initialized,
        "compiled_memory_source": "knowledge/compiled/*.md",
        "kill_switch_path": "data/execution/KILL_EXTERNAL",
        "dry_run": pipeline.config["routing"]["dry_run"],
        "grid_status": "grid_active",
        "model": os.environ.get("OLLAMA_MODEL", "qwen3:8b"),
        "compiler": "aster-compiler-v1",
        "coherence": "continuous",
    }
    payload["architecture"] = "decoupled_grid"
    payload["primary_routes"] = ["/health", "/map_intent", "/transmit"]
    payload["unified_route_enabled"] = False
    payload["jarvis"] = {
        "sole_entry": True,
        "entry_point": JARVIS_ENTRY,
        "bind": f"{JARVIS_HOST}:{JARVIS_PORT}",
        "tasks_registered": len(list_tasks()) if list_tasks else 0,
        "automation_api": "/api/jarvis/tasks",
        "aether_adapter": "read_only",
        "broker_execution": False,
    }
    return payload


@app.get("/healthz")
async def healthz_compat() -> Dict[str, Any]:
    """Same JSON as /health (many stacks probe /healthz)."""
    return await health_check()


@app.get("/health.html", response_class=HTMLResponse)
async def health_html_page() -> str:
    """Human-readable OK page; /health and /healthz stay JSON for automation."""
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>"
        "<title>Jarvis — OK</title></head><body style=\"font-family:system-ui,sans-serif;"
        "margin:2rem;line-height:1.5;\">"
        "<p><strong>Jarvis routing</strong> is running.</p>"
        "<p>JSON probes: <a href=\"/health\">/health</a> · <a href=\"/healthz\">/healthz</a></p>"
        "<p><a href=\"/ui/overview\">Open workbench UI →</a></p>"
        "</body></html>"
    )


def _read_compiled_file(name: str) -> str:
    path = ROOT / "knowledge" / "compiled" / name
    if not path.exists():
        return "Compiled workspace file is missing."
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _tail_lines(path: Path, limit: int = 5) -> list[str]:
    text = _read_text(path).splitlines()
    return text[-limit:] if text else ["No local log lines found."]


def _report_verdict(path: Path) -> str:
    text = _read_text(path)
    if "FINAL VERDICT: PASS" in text:
        return "PASS"
    if "FINAL VERDICT: FAIL" in text:
        return "FAIL"
    return "MISSING"


def _compute_system_verdict() -> str:
    top = DELIVER_DIR / "proof" / "ACCEPTANCE_REPORT.md"
    if not top.exists():
        return "NOT_GENERATED"
    review = _collect_review_artifact()
    real_fixes = [m for m in review["must_fix"] if m not in ("No MUST_FIX entries saved.", "None recorded.", "Unreadable review artifact.")]
    if real_fixes:
        return "BLOCKED"
    modules = [
        DELIVER_DIR / "proof" / "openclaw_v1" / "ACCEPTANCE_REPORT.md",
        DELIVER_DIR / "proof" / "trading" / "ACCEPTANCE_REPORT.md",
        DELIVER_DIR / "proof" / "crypto" / "ACCEPTANCE_REPORT.md",
    ]
    if all(_report_verdict(m) == "PASS" for m in modules):
        return "PASS"
    return "REVIEW"


def _excerpt(path: Path, max_lines: int = 12) -> str:
    lines = [line for line in _read_text(path).splitlines() if line.strip()]
    return "\n".join(lines[:max_lines]) if lines else "No local artifact found."


def _generated_at(path: Path) -> str:
    for line in _read_text(path).splitlines():
        if line.startswith("Generated:"):
            return line.split(":", 1)[1].strip()
    return "UNKNOWN"


def _extract_report_checks(path: Path, limit: int = 6) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in _read_text(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("- PASS - "):
            items.append({"label": stripped.replace("- PASS - ", "", 1), "status": "pass"})
        elif stripped.startswith("- FAIL - "):
            items.append({"label": stripped.replace("- FAIL - ", "", 1), "status": "fail"})
        if len(items) >= limit:
            break
    return items


def _extract_md_section_items(text: str, header: str) -> list[str]:
    lines = text.splitlines()
    capture = False
    items: list[str] = []
    target = f"## {header}".strip()
    for line in lines:
        stripped = line.strip()
        if stripped == target:
            capture = True
            continue
        if capture and stripped.startswith("## "):
            break
        if capture and stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _status_tone(status: str) -> str:
    lowered = (status or "").lower()
    if "pass" in lowered:
        return "pass"
    if "fail" in lowered:
        return "fail"
    if lowered in {"ready", "present", "captured", "ok"}:
        return "ready"
    if lowered in {"missing", "blocked", "partial"}:
        return "blocked"
    return "neutral"


def _display_status(status: str) -> str:
    lowered = (status or "").lower()
    mapping = {
        "pass": "Ready",
        "fail": "Needs attention",
        "missing": "Awaiting artifact",
        "partial": "In progress",
        "present": "Available",
        "captured": "Available",
        "ready": "Ready",
        "blocked": "Blocked",
        "active": "Active",
        "ok": "Ready",
    }
    return mapping.get(lowered, status or "Unknown")


def _display_role(role: str) -> str:
    mapping = {
        "Lyra": "Instruction",
        "Aster": "Compile",
        "澈": "Review",
        "Cursor": "Executor",
        "Review / Decide": "Decide",
    }
    return mapping.get(role, role or "unknown")


def _executor_mode(owner: str) -> str:
    return "automation" if owner == "Cursor" else "local"


def _short_rel(path_str: str, max_len: int = 44) -> str:
    if len(path_str) <= max_len:
        return path_str
    return "…" + path_str[-(max_len - 1) :]


def _handoff_line(h: HandoffRecord) -> str:
    return f"{_display_role(h.from_role)} → {_display_role(h.to_role)} · {_display_status(h.status)}"


def _stage_summary(block: RoundBlock) -> str:
    if not block.body:
        return "No local detail saved yet."
    first = next((line.strip() for line in block.body.splitlines() if line.strip()), "")
    return first or "No local detail saved yet."


def _round_stage_panels(round_item: CollaborationRound) -> list[dict[str, str]]:
    def _panel(block: RoundBlock, section: str) -> dict[str, str]:
        return {
            "section": section,
            "title": section,
            "lead": _display_role(block.owner),
            "executor_mode": _executor_mode(block.owner),
            "status": _display_status(block.status),
            "tone": _status_tone(block.status),
            "artifact": block.artifact_path,
            "summary": _stage_summary(block),
            "details": block.body,
        }

    return [
        _panel(round_item.input_block, "Instruction"),
        _panel(round_item.compile_pack_block, "Compile"),
        _panel(round_item.audit_block, "Review"),
        _panel(round_item.execution_result, "Execute"),
        _panel(round_item.decision_block, "Decide"),
    ]


def _collect_review_artifact() -> dict[str, Any]:
    review_path = DELIVER_DIR / "review" / "claude_review.json"
    if not review_path.exists():
        return {
            "status": "No audit artifact found locally.",
            "must_fix": ["No MUST_FIX entries saved."],
            "optional": ["No OPTIONAL entries saved."],
        }
    try:
        payload = json.loads(review_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "status": "Saved audit artifact is unreadable.",
            "must_fix": ["Unreadable review artifact."],
            "optional": ["None."],
        }
    return {
        "status": "Audit artifact present.",
        "must_fix": payload.get("MUST_FIX") or ["None recorded."],
        "optional": payload.get("OPTIONAL") or ["None recorded."],
    }


def _build_collaboration_rounds() -> list[CollaborationRound]:
    review = _collect_review_artifact()
    cursor_pack = DELIVER_DIR / "cursor" / "CursorPack.md"
    proof_path = DELIVER_DIR / "proof" / "ACCEPTANCE_REPORT.md"
    top_verdict = _report_verdict(proof_path)
    generated = _generated_at(proof_path)
    round_id = f"round-{generated.replace(':', '').replace('-', '').replace('T', '-').replace('Z', '')}" if generated != "UNKNOWN" else "round-local-001"

    lyra_source = DELIVER_DIR / "spec" / "build_spec.md"
    if lyra_source.exists():
        lyra_body = _excerpt(lyra_source, 14)
        lyra_status = "captured"
        lyra_artifact = str(lyra_source.relative_to(ROOT))
    else:
        lyra_body = (
            "No instruction artifact found locally.\n\n"
            "Drop a spec into deliver/spec/build_spec.md, then refresh. "
            "Context excerpt from knowledge/source/ASTER.md follows:\n\n"
            + _excerpt(ROOT / "knowledge" / "source" / "ASTER.md", 12)
        )
        lyra_status = "missing"
        lyra_artifact = str((ROOT / "knowledge" / "source" / "ASTER.md").relative_to(ROOT))

    audit_body = "\n".join(
        [f"MUST_FIX: {item}" for item in review["must_fix"]]
        + [f"OPTIONAL: {item}" for item in review["optional"]]
    )
    audit_status = "present" if "present" in review["status"].lower() else "missing"
    audit_artifact = "deliver/review/claude_review.json" if (DELIVER_DIR / "review" / "claude_review.json").exists() else ""

    compile_body = (
        "Compiled pack present.\n\n" + _excerpt(cursor_pack, 8)
        if cursor_pack.exists()
        else "No saved compiled pack artifact found locally."
    )
    compile_status = "present" if cursor_pack.exists() else "missing"

    decision_body = "\n".join(
        [
            f"Top-level verdict: {top_verdict}",
            "Decision basis: local proof artifacts only.",
            f"OpenClaw: {_report_verdict(DELIVER_DIR / 'proof' / 'openclaw_v1' / 'ACCEPTANCE_REPORT.md')}",
            f"Trading: {_report_verdict(DELIVER_DIR / 'proof' / 'trading' / 'ACCEPTANCE_REPORT.md')}",
            f"Crypto: {_report_verdict(DELIVER_DIR / 'proof' / 'crypto' / 'ACCEPTANCE_REPORT.md')}",
        ]
    )

    execution_body = "\n".join(
        [
            "Acceptance command: ./scripts/accept.sh",
            f"Execution result: {top_verdict}",
            "Latest local audit lines:",
            *(_tail_lines(LOGS_DIR / "audit.log", 4)),
        ]
    )

    h1 = HandoffRecord(
        from_role="Lyra",
        to_role="Aster",
        status="ready" if lyra_status == "captured" else "partial",
        artifact_path=lyra_artifact,
        summary="Instruction/spec source for compile step.",
    )
    h2 = HandoffRecord(
        from_role="Aster",
        to_role="澈",
        status="ready" if compile_status == "present" else "missing",
        artifact_path=str(cursor_pack.relative_to(ROOT)) if cursor_pack.exists() else "",
        summary="Compiled pack handed to audit layer.",
    )
    h3 = HandoffRecord(
        from_role="澈",
        to_role="Review / Decide",
        status="ready" if audit_status == "present" else "missing",
        artifact_path=audit_artifact,
        summary="Audit output forwarded for decide step.",
    )
    h4 = HandoffRecord(
        from_role="Review / Decide",
        to_role="Cursor",
        status="ready",
        artifact_path=str(proof_path.relative_to(ROOT)),
        summary="Execution and proof state available locally.",
    )
    for h in (h1, h2, h3, h4):
        h.display_line = _handoff_line(h)
    handoffs = [h1, h2, h3, h4]

    round_item = CollaborationRound(
        round_id=round_id,
        status=top_verdict,
        owner="Review / Decide" if top_verdict == "PASS" else "Cursor",
        input_block=RoundBlock(
            owner="Lyra",
            status=lyra_status,
            title="Input Block",
            body=lyra_body,
            artifact_path=lyra_artifact,
        ),
        audit_block=RoundBlock(
            owner="澈",
            status=audit_status,
            title="Audit Block",
            body=audit_body,
            artifact_path=audit_artifact,
        ),
        compile_pack_block=RoundBlock(
            owner="Aster",
            status=compile_status,
            title="Compile Pack Block",
            body=compile_body,
            artifact_path=str(cursor_pack.relative_to(ROOT)) if cursor_pack.exists() else "",
        ),
        decision_block=RoundBlock(
            owner="Review / Decide",
            status=top_verdict,
            title="Decision Block",
            body=decision_body,
            artifact_path=str(proof_path.relative_to(ROOT)),
        ),
        execution_result=RoundBlock(
            owner="Cursor",
            status=top_verdict,
            title="Execution Result",
            body=execution_body,
            artifact_path=str(proof_path.relative_to(ROOT)),
        ),
        proof_link=str(proof_path.relative_to(ROOT)),
        handoffs=handoffs,
    )
    return [round_item]


def _find_bottleneck(latest: CollaborationRound | None = None) -> str:
    if latest is None:
        latest = _build_collaboration_rounds()[0]
    if latest.input_block.status in ("missing", "partial"):
        return "Instruction artifact not found locally."
    if latest.compile_pack_block.status in ("missing", "blocked"):
        return "Compile pack not found locally."
    if latest.audit_block.status in ("missing", "blocked"):
        return "Audit artifact not found locally."
    return "No blocking artifact."


def _collect_workbench_context() -> dict[str, Any]:
    rounds = _build_collaboration_rounds()
    latest = rounds[0]
    oc = _report_verdict(DELIVER_DIR / "proof" / "openclaw_v1" / "ACCEPTANCE_REPORT.md")
    tr = _report_verdict(DELIVER_DIR / "proof" / "trading" / "ACCEPTANCE_REPORT.md")
    cr = _report_verdict(DELIVER_DIR / "proof" / "crypto" / "ACCEPTANCE_REPORT.md")
    module_strip = [
        {"label": "OpenClaw", "value": oc, "tone": _status_tone(oc)},
        {"label": "Trading", "value": tr, "tone": _status_tone(tr)},
        {"label": "Crypto", "value": cr, "tone": _status_tone(cr)},
    ]
    proof_top = DELIVER_DIR / "proof" / "ACCEPTANCE_REPORT.md"
    proof_label = "Available" if proof_top.exists() else "Awaiting artifact"
    bottleneck = _find_bottleneck(latest)
    return {
        "title": "Active round desk",
        "subtitle": "Current round status and the next local action.",
        "show_core_seg": True,
        "rounds": [latest],
        "acceptance_command": "./scripts/accept.sh",
        "recent_audit": _tail_lines(LOGS_DIR / "audit.log", 4),
        "selected_round": latest,
        "stage_panels": _round_stage_panels(latest),
        "shell_mode": "workbench",
        "module_strip": module_strip,
        "proof_label": proof_label,
        "bottleneck": bottleneck,
    }


def _collect_aether_nexus_context() -> dict[str, Any]:
    aether_panel: dict[str, Any] = {"available": False, "read_only": True}
    if load_aether_snapshot is not None:
        try:
            aether_panel = load_aether_snapshot(write_artifact=False)
        except Exception as exc:
            aether_panel = {"available": False, "read_only": True, "error": str(exc)}

    status = aether_panel.get("status") if isinstance(aether_panel.get("status"), dict) else {}
    candidates = aether_panel.get("candidates") if isinstance(aether_panel.get("candidates"), dict) else {}
    dryrun = aether_panel.get("dryrun_signals") if isinstance(aether_panel.get("dryrun_signals"), dict) else {}
    validation = aether_panel.get("validation") if isinstance(aether_panel.get("validation"), dict) else {}

    return {
        "title": "Aether Nexus",
        "subtitle": "Trading sidecar — IB dry-run, options scan, Streamlit dashboard on :8510.",
        "show_core_seg": False,
        "page_kind": "aether_nexus",
        "nexus_dashboard_url": AETHER_NEXUS_URL,
        "nexus_start_cmd": "./aether_nexus/run_all.sh",
        "nexus_available": bool(aether_panel.get("available")),
        "nexus_reason": aether_panel.get("reason", ""),
        "daemon_connected": validation.get("daemon_connected", False),
        "live_trading_enabled": validation.get("live_trading_enabled", False),
        "candidate_count": candidates.get("row_count", 0),
        "candidate_symbols": candidates.get("symbols") or [],
        "latest_scan_time": candidates.get("scan_timestamp") or dryrun.get("latest_scan_time") or "—",
        "signal_count": dryrun.get("count", 0),
        "top_symbols": dryrun.get("top_symbols") or [],
        "top_pick": dryrun.get("top_pick") or "—",
        "aether_readonly": aether_panel,
        "sidecar_ports": [
            {"label": "9B Gateway", "port": 8501, "role": "LM Mini / compile gateway"},
            {"label": "Aether Nexus", "port": AETHER_NEXUS_PORT, "role": "Trading dashboard + daemon"},
            {"label": "Aether Watcher", "port": 8520, "role": "Watch targets monitor"},
        ],
        "jarvis_snapshot_task": "aether.snapshot.readonly",
        "jarvis_automation_api": "/api/jarvis/tasks",
        "status_message": status.get("message") or status.get("status") or "—",
        "cards": [],
        "sections": [],
        "side_panel": [],
    }


_CRYPTO_DIR = DELIVER_DIR / "crypto"
_CRYPTO_EVIDENCE_DIR = _CRYPTO_DIR / "evidence"
_CRYPTO_REGISTRY_PATH = _CRYPTO_DIR / "rwa_registry.json"
_CRYPTO_PROOF_CANDIDATES_PATH = _CRYPTO_DIR / "proof_candidates.json"
_CRYPTO_SCAN_SOURCES_PATH = _CRYPTO_DIR / "scan_sources.json"
_CRYPTO_SCAN_LAST_RUN_PATH = _CRYPTO_DIR / "scan_last_run.json"
_CRYPTO_SCAN_CMD = "./scripts/scan_crypto_rwa_public.sh"

_CRYPTO_RWA_PURPOSE = (
    "Research and proof layer for RWA, stablecoins, on-chain identity, wallets, "
    "programmable payments, and AI-agent financial rails. Generates local maps, "
    "evidence cards, risk notes, and proof-pack candidates under outputs/crypto_rwa/. "
    "No wallet connection, trading, or live API calls in V1."
)

_CRYPTO_AGENT_ROLE = [
    "Generate infrastructure maps and evidence cards to outputs/crypto_rwa/",
    "Create risk notes and proof-pack candidates from local research posture",
    "Identify unknowns and flag items for 澄 review",
    "Prepare research tasks from section registry and evidence on disk",
    "Scan allowlisted public URLs via ./scripts/scan_crypto_rwa_public.sh (optional)",
    "Never connect wallets or request private keys",
    "Never execute transactions or trade",
    "Never call live crypto APIs in this version",
    "Never claim incomplete evidence is verified",
    "Never generate investment advice",
]

_CRYPTO_AGENT_CANNOT = [
    "Connect wallets",
    "Request private keys",
    "Execute transactions",
    "Trade",
    "Call live crypto APIs in this version",
    "Claim live market data",
    "Generate investment advice",
    "Pretend incomplete evidence is verified",
]

_CRYPTO_RISK_BOUNDARIES = [
    "No wallet connection in V1",
    "Research / proof / risk only",
    "No transaction execution",
    "No private key input",
    "No price-ticker or trading UI",
]

def _load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(_read_text(path))
    except json.JSONDecodeError:
        return default


def _load_crypto_evidence_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    if not _CRYPTO_EVIDENCE_DIR.exists():
        return cards
    for path in sorted(_CRYPTO_EVIDENCE_DIR.glob("*.json")):
        data = _load_json_file(path, None)
        if not isinstance(data, dict) or not data.get("id"):
            continue
        cards.append(
            {
                **data,
                "file_path": str(path.relative_to(ROOT)),
                "source_kind": data.get("source_kind") or "webpage_archive",
            }
        )
    return cards


def _load_onchain_live() -> dict[str, Any]:
    """Receipt-backed on-chain facts only. Old webpage cards are not a fallback."""
    try:
        from app.crypto_rwa.rwa_chain_connect import load_published
        pub = load_published()
    except Exception as exc:
        return {
            "connected": False,
            "stale": True,
            "error": str(exc)[:160],
            "receipts": [],
            "asof": None,
        }
    if pub.get("status") == "empty":
        return {**pub, "label": "no on-chain receipt yet"}
    return {
        **pub,
        "label": "last_success" if pub.get("stale") else "asof",
        "webpage_cards_are_reference": True,
    }


def _load_crypto_rwa_registry() -> dict[str, Any]:
    return _load_json_file(_CRYPTO_REGISTRY_PATH, {"sections": [], "artifacts": []})


def _load_crypto_proof_candidates() -> list[dict[str, Any]]:
    data = _load_json_file(_CRYPTO_PROOF_CANDIDATES_PATH, [])
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        rel = str(item["path"])
        out.append(
            {
                **item,
                "path": rel,
                "exists": (ROOT / rel).exists(),
            }
        )
    return out


def _enrich_crypto_rwa_sections(registry: dict[str, Any], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for card in cards:
        section_id = str(card.get("section", ""))
        counts[section_id] = counts.get(section_id, 0) + 1

    sections: list[dict[str, Any]] = []
    for raw in registry.get("sections", []):
        if not isinstance(raw, dict):
            continue
        section_id = str(raw.get("id", ""))
        registry_path = str(raw.get("registry_path", ""))
        card_count = counts.get(section_id, 0)
        registry_exists = bool(registry_path and (ROOT / registry_path).exists())
        status = str(raw.get("status", "empty"))
        if card_count > 0 and status == "empty":
            status = "active"
        sections.append(
            {
                "id": section_id,
                "title": raw.get("title", section_id),
                "summary": raw.get("summary", ""),
                "registry_path": registry_path,
                "registry_exists": registry_exists,
                "card_count": card_count,
                "status": status,
            }
        )
    return sections


def _load_crypto_artifacts(registry: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in registry.get("artifacts", []):
        if not isinstance(raw, dict) or not raw.get("path"):
            continue
        rel = str(raw["path"])
        out.append(
            {
                "path": rel,
                "description": raw.get("description", ""),
                "exists": (ROOT / rel).exists(),
            }
        )
    return out


def _load_crypto_scan_status() -> dict[str, Any]:
    last_run = _load_json_file(_CRYPTO_SCAN_LAST_RUN_PATH, {})
    if not isinstance(last_run, dict):
        last_run = {}
    sources = _load_json_file(_CRYPTO_SCAN_SOURCES_PATH, {})
    source_count = len(sources.get("sources", [])) if isinstance(sources, dict) else 0
    counts = last_run.get("counts", {}) if isinstance(last_run.get("counts"), dict) else {}
    return {
        "command": _CRYPTO_SCAN_CMD,
        "sources_path": str(_CRYPTO_SCAN_SOURCES_PATH.relative_to(ROOT)),
        "last_run_path": str(_CRYPTO_SCAN_LAST_RUN_PATH.relative_to(ROOT)),
        "source_count": source_count,
        "has_run": _CRYPTO_SCAN_LAST_RUN_PATH.exists(),
        "ran_at": last_run.get("ran_at", "never"),
        "ok": counts.get("ok", 0),
        "warn": counts.get("warn", 0),
        "fail": counts.get("fail", 0),
        "results": last_run.get("results", []) if isinstance(last_run.get("results"), list) else [],
    }


def _collect_crypto_context(
    selected_tab: str = "delivery",
    *,
    flash: str = "",
    flash_file: str = "",
    flash_error: str = "",
) -> dict[str, Any]:
    _ = selected_tab  # tab query retained for route compatibility; V1 UI is single-track
    report_v03 = DELIVER_DIR / "proof" / "crypto" / "ACCEPTANCE_REPORT_v0_3.md"
    report_v02 = DELIVER_DIR / "proof" / "crypto" / "ACCEPTANCE_REPORT.md"
    report_path = report_v03 if report_v03.exists() else report_v02
    proof_generated = "UNKNOWN"
    for line in _read_text(report_path).splitlines():
        if line.startswith("generated_at:"):
            proof_generated = line.split(":", 1)[1].strip()
            break
        if line.startswith("Generated:"):
            proof_generated = line.split(":", 1)[1].strip()
            break

    registry = _load_crypto_rwa_registry()
    evidence_cards = _load_crypto_evidence_cards()
    review_queue = [c for c in evidence_cards if c.get("needs_cheng_review")]
    rwa_sections = _enrich_crypto_rwa_sections(registry, evidence_cards)
    proof_candidates = _load_crypto_proof_candidates()
    artifacts = _load_crypto_artifacts(registry)
    scan_status = _load_crypto_scan_status()
    pack_status = read_crypto_rwa_pack_status()
    pack_completeness = [
        {"key": "rwa_infrastructure_map", "label": "rwa_infrastructure_map.md", "done": pack_status.get("rwa_infrastructure_map", False)},
        {"key": "stablecoin_evidence_card", "label": "stablecoin_evidence_card.md", "done": pack_status.get("stablecoin_evidence_card", False)},
        {"key": "agent_payment_risk_note", "label": "agent_payment_risk_note.md", "done": pack_status.get("agent_payment_risk_note", False)},
        {"key": "rwa_proof_pack_candidate", "label": "rwa_proof_pack_candidate.md", "done": pack_status.get("rwa_proof_pack_candidate", False)},
    ]
    crypto_intake = load_crypto_intake()
    onchain_live = _load_onchain_live()

    return {
        "title": "Crypto / RWA Sovereignty",
        "subtitle": "Research and proof layer — local file generation, no wallet in V1.",
        "show_core_seg": False,
        "page_kind": "crypto",
        "purpose": _CRYPTO_RWA_PURPOSE,
        "rwa_sections": rwa_sections,
        "evidence_cards": evidence_cards,
        "evidence_count": len(evidence_cards),
        "onchain_live": onchain_live,
        "review_queue": review_queue,
        "proof_candidates": proof_candidates,
        "artifacts": artifacts,
        "scan_status": scan_status,
        "pack_status": pack_status,
        "pack_completeness": pack_completeness,
        "crypto_intake": crypto_intake.__dict__,
        "output_dir": str(CRYPTO_RWA_OUTPUT_DIR.relative_to(ROOT)),
        "registry_path": str(_CRYPTO_REGISTRY_PATH.relative_to(ROOT)),
        "evidence_dir": str(_CRYPTO_EVIDENCE_DIR.relative_to(ROOT)),
        "agent_role": _CRYPTO_AGENT_ROLE,
        "agent_cannot": _CRYPTO_AGENT_CANNOT,
        "risk_boundaries": _CRYPTO_RISK_BOUNDARIES,
        "flash": flash,
        "flash_file": flash_file,
        "flash_error": flash_error,
        "quick_status": {
            "proof_verdict": _report_verdict(report_path),
            "proof_generated": proof_generated,
            "proof_path": str(report_path.relative_to(ROOT)),
            "posture": "local-first / research-only / no-wallet",
            "acceptance_cmd": "./scripts/accept_crypto_rwa_functional.sh",
            "acceptance_active": "active",
            "evidence_count": len(evidence_cards),
            "review_count": len(review_queue),
            "scan_ran_at": scan_status.get("ran_at", "never"),
            "pack_complete": pack_status.get("pack_complete", False),
        },
        "proof_acceptance": {
            "command": "bash scripts/accept_crypto_v0_3.sh",
            "report_path": "deliver/proof/crypto/ACCEPTANCE_REPORT_v0_3.md",
        },
        "cards": [],
        "sections": [],
        "side_panel": [],
    }


def _collect_proofpack_context() -> dict[str, Any]:
    top = DELIVER_DIR / "proof" / "ACCEPTANCE_REPORT.md"
    return {
        "title": "Proof",
        "subtitle": "Proof paths, verdicts, and recent audit lines.",
        "show_core_seg": True,
        "cards": [
            {"label": "Top-Level", "value": _report_verdict(top), "tone": _status_tone(_report_verdict(top)), "meta": _generated_at(top)},
            {"label": "OpenClaw", "value": _report_verdict(DELIVER_DIR / 'proof' / 'openclaw_v1' / 'ACCEPTANCE_REPORT.md'), "tone": _status_tone(_report_verdict(DELIVER_DIR / 'proof' / 'openclaw_v1' / 'ACCEPTANCE_REPORT.md'))},
            {"label": "Trading", "value": _report_verdict(DELIVER_DIR / 'proof' / 'trading' / 'ACCEPTANCE_REPORT.md'), "tone": _status_tone(_report_verdict(DELIVER_DIR / 'proof' / 'trading' / 'ACCEPTANCE_REPORT.md'))},
            {"label": "Crypto", "value": _report_verdict(DELIVER_DIR / 'proof' / 'crypto' / 'ACCEPTANCE_REPORT.md'), "tone": _status_tone(_report_verdict(DELIVER_DIR / 'proof' / 'crypto' / 'ACCEPTANCE_REPORT.md'))},
        ],
        "sections": [
            {"title": "Proof Paths", "kind": "paths", "items": [
                {"label": "Top-Level", "value": "deliver/proof/ACCEPTANCE_REPORT.md"},
                {"label": "OpenClaw", "value": "deliver/proof/openclaw_v1/ACCEPTANCE_REPORT.md"},
                {"label": "Trading", "value": "deliver/proof/trading/ACCEPTANCE_REPORT.md"},
                {"label": "Crypto", "value": "deliver/proof/crypto/ACCEPTANCE_REPORT.md"},
            ]},
            {"title": "Module Verdicts", "kind": "checklist", "items": [
                {"label": "OpenClaw Senior V1", "status": _status_tone(_report_verdict(DELIVER_DIR / 'proof' / 'openclaw_v1' / 'ACCEPTANCE_REPORT.md'))},
                {"label": "Trading Module", "status": _status_tone(_report_verdict(DELIVER_DIR / 'proof' / 'trading' / 'ACCEPTANCE_REPORT.md'))},
                {"label": "Crypto V1", "status": _status_tone(_report_verdict(DELIVER_DIR / 'proof' / 'crypto' / 'ACCEPTANCE_REPORT.md'))},
            ]},
            {"title": "Latest Audit Snapshot", "kind": "activity", "items": _tail_lines(LOGS_DIR / "audit.log", 8)},
        ],
        "side_panel": [
            {"title": "Commands", "kind": "paths", "items": [
                {"label": "Top-Level Acceptance", "value": "./scripts/accept.sh"},
                {"label": "Crypto Acceptance", "value": "./scripts/accept_crypto_v1.sh"},
            ]},
            {"title": "Generated Timestamp", "kind": "rows", "items": [
                {"label": "Generated", "value": _generated_at(top)},
                {"label": "Final Verdict", "value": _report_verdict(top), "tone": _status_tone(_report_verdict(top))},
            ]},
        ],
    }


def _collect_proof_pack_context() -> dict[str, Any]:
    pp_dir = DELIVER_DIR / "proof_pack"
    required_artifacts = [
        "TEMPLATE_REPO.md",
        "INJECTOR_SPEC.md",
        "SCOPEGATE_RULES.md",
        "REFERENCE_IMPL.md",
    ]
    artifacts = []
    for art in required_artifacts:
        exists = (pp_dir / art).exists()
        artifacts.append({"label": art, "status": "pass" if exists else "blocked"})
    report_path = pp_dir / "ACCEPTANCE_REPORT.md"
    verdict = _report_verdict(report_path)
    return {
        "title": "Proof Pack",
        "subtitle": "Packaged proof product — build status, pricing, and acceptance.",
        "page_kind": "proof_pack",
        "verdict": verdict,
        "verdict_tone": _status_tone(verdict),
        "pricing": [
            {"tier": "Lite", "price": "$3,500"},
            {"tier": "Pro", "price": "$7,000"},
            {"tier": "Maintenance", "price": "$500 + $1,000/mo"},
        ],
        "build_status": [
            {"label": "Template repo", "done": (pp_dir / "TEMPLATE_REPO.md").exists()},
            {"label": "Injector tool", "done": (pp_dir / "INJECTOR_SPEC.md").exists()},
            {"label": "Scopegate", "done": (pp_dir / "SCOPEGATE_RULES.md").exists()},
            {"label": "Reference implementations", "done": (pp_dir / "REFERENCE_IMPL.md").exists()},
        ],
        "artifacts": artifacts,
        "acceptance_cmd": "./scripts/accept_proof_pack.sh",
        "next_action": "Build template repo + scopegate before sales copy.",
        "cards": [],
        "sections": [],
        "side_panel": [],
    }


def _parse_flutter_link_report(report_path: Path) -> dict[str, Any]:
    """Read SENIOR_FLUTTER_LINK_REPORT.md and return structured data."""
    text = _read_text(report_path)
    files: list[dict[str, str]] = []
    gates: list[dict[str, str]] = []
    runtime = "UNKNOWN"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- PRESENT"):
            files.append({"label": stripped.split("|", 1)[-1].strip(), "status": "pass"})
        elif stripped.startswith("- MISSING"):
            files.append({"label": stripped.split("|", 1)[-1].strip(), "status": "blocked"})
        elif stripped.startswith("- PASS  |"):
            gates.append({"label": stripped.split("|", 1)[-1].strip(), "status": "pass"})
        elif stripped.startswith("- FAIL  |"):
            gates.append({"label": stripped.split("|", 1)[-1].strip(), "status": "blocked"})
        elif stripped.startswith("UNKNOWN") or stripped.startswith("Flutter"):
            runtime = stripped
    return {"files": files, "gates": gates, "runtime": runtime}


def _collect_senior_v2_context() -> dict[str, Any]:
    report_path = DELIVER_DIR / "proof" / "openclaw_v1" / "ACCEPTANCE_REPORT.md"
    link_report_path = DELIVER_DIR / "proof" / "openclaw_v1" / "SENIOR_FLUTTER_LINK_REPORT.md"
    senior_md = _read_compiled_file("WORKSPACE_senior.md")
    home_path = CLIENT_DIR / "lib" / "features" / "home" / "home_page.dart"
    controller_path = CLIENT_DIR / "lib" / "features" / "home" / "home_controller.dart"
    home_text = _read_text(home_path)
    controller_text = _read_text(controller_path)

    # File-backed checklist — greps live source files directly
    def _grep(rel: str, token: str) -> str:
        f = CLIENT_DIR / rel
        return "pass" if f.exists() and token in _read_text(f) else "blocked"

    checklist = [
        {"label": "Presence Echo (我在)", "status": _grep("lib/features/home/home_page.dart", "我在")},
        {"label": "Verified Mode hard gate", "status": _grep("lib/core/services/verified_mode_service.dart", "medication")},
        {"label": "48/60/72h chain (ESCALATE_72H)", "status": _grep("lib/core/services/safety_chain_service.dart", "ESCALATE_72H")},
        {"label": "TTS marker (TTS_SPOKEN)", "status": _grep("lib/core/services/tts_service.dart", "TTS_SPOKEN")},
        {"label": "Log service (WOULD_NOTIFY)", "status": _grep("lib/core/services/log_service.dart", "WOULD_NOTIFY")},
        {"label": "Core task tokens (你在吗/不舒服/叫家人)", "status": "pass" if all(t in controller_text for t in ["你在吗", "不舒服", "叫家人"]) else "blocked"},
    ]

    # File existence list
    tracked_files = [
        "lib/main.dart",
        "lib/features/home/home_page.dart",
        "lib/features/home/home_controller.dart",
        "lib/features/safety/safety_screen.dart",
        "lib/core/services/tts_service.dart",
        "lib/core/services/log_service.dart",
        "lib/core/services/presence_echo_service.dart",
        "lib/core/services/safety_chain_service.dart",
        "lib/core/services/verified_mode_service.dart",
        "pubspec.yaml",
    ]
    flutter_files = [
        {"label": rel, "status": "pass" if (CLIENT_DIR / rel).exists() else "blocked"}
        for rel in tracked_files
    ]

    # Link report verdict
    link_verdict = _report_verdict(link_report_path) if link_report_path.exists() else "NOT_RUN"
    link_generated = _generated_at(link_report_path) if link_report_path.exists() else "—"

    # Flutter SDK runtime
    import shutil
    flutter_runtime = "UNKNOWN — Flutter SDK not installed (file checks only)" if not shutil.which("flutter") else "PRESENT"

    senior_ia_groups = [
        {"title": "TOP", "items": ["不舒服 / 需要帮助", "叫家人", "没药了 / 药 / 保健品"]},
        {"title": "MIDDLE", "items": ["好 / 一般 / 不太好", "想聊天", "今天的提醒 / 今天要做的事", "今天吃什么"]},
        {"title": "BOTTOM", "items": ["Wi-Fi断了 / 手机问题", "更多功能", "翻译 / 视频翻译助手"]},
    ]
    senior_paths = [
        {"label": "Client root", "short": _short_rel(str(CLIENT_DIR.relative_to(ROOT))), "full": str(CLIENT_DIR.relative_to(ROOT))},
        {"label": "Home file", "short": _short_rel(str(home_path.relative_to(ROOT))), "full": str(home_path.relative_to(ROOT))},
        {"label": "Controller", "short": _short_rel(str(controller_path.relative_to(ROOT))), "full": str(controller_path.relative_to(ROOT))},
        {"label": "Link Report", "short": _short_rel(str(link_report_path.relative_to(ROOT))), "full": str(link_report_path.relative_to(ROOT))},
        {"label": "Proof", "short": _short_rel(str(report_path.relative_to(ROOT))), "full": str(report_path.relative_to(ROOT))},
    ]
    verdict = _report_verdict(report_path)
    return {
        "title": "Senior",
        "subtitle": "OpenClaw Senior V1 — file-backed Flutter client status.",
        "show_core_seg": False,
        "page_kind": "senior",
        "cards": [
            {"label": "Proof", "value": verdict, "tone": _status_tone(verdict), "meta": str(report_path.relative_to(ROOT))},
            {"label": "Link Report", "value": link_verdict, "tone": _status_tone(link_verdict), "meta": link_generated},
            {"label": "Flutter Runtime", "value": flutter_runtime, "tone": "neutral"},
            {"label": "External", "value": "off", "tone": "ready"},
        ],
        "senior_ia_groups": senior_ia_groups,
        "senior_checklist": checklist,
        "senior_flutter_files": flutter_files,
        "senior_paths": senior_paths,
        "senior_log_lines": _tail_lines(LOGS_DIR / "audit.log", 6),
        "acceptance_cmd": "./scripts/accept_senior_flutter_link.sh",
        "rule_note": "File-backed checks only. Flutter SDK absent → runtime UNKNOWN, not FAIL.",
        "sections": [
            {"title": "V1 Hard Gates (file-backed)", "kind": "checklist", "items": checklist},
            {"title": "Guardrails", "kind": "chips", "items": [
                "medication advice disabled",
                "food suggestion disabled",
                "supplement checking disabled",
                "camera OCR placeholder only",
            ]},
            {"title": "Current State", "kind": "activity", "items": _extract_md_section_items(senior_md, "Current Next Actions")},
        ],
        "side_panel": [
            {"title": "References", "kind": "paths", "items": [
                {"label": "Client Path", "value": str(CLIENT_DIR.relative_to(ROOT))},
                {"label": "Link Report", "value": str(link_report_path.relative_to(ROOT))},
                {"label": "Proof", "value": str(report_path.relative_to(ROOT))},
            ]},
        ],
    }


def _intake_from_form(
    customer_type: str = "",
    current_device: str = "",
    target_use_case: str = "",
    privacy_sensitivity: str = "",
    desired_local_functions: str = "",
    budget_range: str = "",
) -> Intake:
    return Intake(
        customer_type=customer_type.strip(),
        current_device=current_device.strip(),
        target_use_case=target_use_case.strip(),
        privacy_sensitivity=privacy_sensitivity.strip(),
        desired_local_functions=desired_local_functions.strip(),
        budget_range=budget_range.strip(),
    )


def _collect_local_ai_nodes_context(*, flash: str = "", flash_file: str = "", flash_error: str = "") -> dict[str, Any]:
    intake = load_intake()
    pack_status = read_pack_status()
    completeness = [
        {"key": "pilot_brief", "label": "pilot_brief.md", "done": pack_status.get("pilot_brief", False)},
        {"key": "package_recommendation", "label": "package_recommendation.json", "done": pack_status.get("package_recommendation", False)},
        {"key": "delivery_checklist", "label": "delivery_checklist.md", "done": pack_status.get("delivery_checklist", False)},
        {"key": "delivery_timeline", "label": "delivery_timeline.md", "done": pack_status.get("delivery_timeline", False)},
        {"key": "agent_roles", "label": "agent_roles.md", "done": pack_status.get("agent_roles", False)},
    ]
    tiers = [
        {"name": name, **data} for name, data in TIERS.items()
    ]
    return {
        "title": "Private Local AI Nodes",
        "subtitle": "Local AI capability deployment for private workflows.",
        "show_core_seg": False,
        "page_kind": "local_ai_nodes",
        "purpose": (
            "Package and deliver local AI node setups: OCR → Markdown → Obsidian/RAG → "
            "Local Qwen → FastAPI/local router → iPhone/iPad/Mac access."
        ),
        "intake": intake.to_dict(),
        "pack_status": pack_status,
        "pack_completeness": completeness,
        "output_dir": str(OUTPUT_DIR.relative_to(ROOT)),
        "tiers": tiers,
        "best_fit_customers": BEST_FIT,
        "not_target_customers": NOT_TARGET,
        "flash": flash,
        "flash_file": flash_file,
        "flash_error": flash_error,
        "agent_work": [
            "Intake analysis: customer type, privacy level, hardware gap, package tier",
            "Delivery generation: brief, recommendation, checklist, timeline, roles",
            "Review routing: 澄 for privacy/security; Lyra for pricing ambiguity",
            "Output pack generation under outputs/local_ai_node/",
        ],
        "agent_bans": [
            "No payment connection",
            "No Shopify or hardware purchase",
            "No external API calls from generator",
            "No fake compatibility promises",
            "No private customer data upload in module",
        ],
        "cards": [],
        "sections": [],
        "side_panel": [],
    }


def _collect_overview_context() -> dict[str, Any]:
    r = _build_collaboration_rounds()[0]
    sv = _compute_system_verdict()
    bottleneck = _find_bottleneck()

    def _mod(name: str, proof_rel: str, accept_cmd: str, next_act: str, status: str | None = None, **extra: Any) -> dict[str, Any]:
        path = ROOT / proof_rel
        verdict = status if status is not None else _report_verdict(path)
        return {
            "name": name,
            "status": verdict,
            "tone": _status_tone(verdict),
            "proof_path": proof_rel,
            "acceptance_cmd": accept_cmd,
            "next_action": next_act,
            **extra,
        }

    registry = _load_crypto_rwa_registry()
    evidence_cards = _load_crypto_evidence_cards()
    rwa_sections = _enrich_crypto_rwa_sections(registry, evidence_cards)

    pack_status = read_pack_status()
    pack_next = (
        "Pack complete — review outputs/local_ai_node/"
        if pack_status.get("pack_complete")
        else "Run Export Local AI Node Pack or generate missing artifacts."
    )

    pack_label = "PASS" if pack_status.get("pack_complete") else ("PARTIAL" if any(
        pack_status.get(k) for k in ("pilot_brief", "package_recommendation", "delivery_checklist", "delivery_timeline", "agent_roles")
    ) else "EMPTY")

    crypto_pack = read_crypto_rwa_pack_status()
    crypto_pack_label = "PASS" if crypto_pack.get("pack_complete") else (
        "PARTIAL" if any(crypto_pack.get(k) for k in (
            "rwa_infrastructure_map", "stablecoin_evidence_card", "agent_payment_risk_note", "rwa_proof_pack_candidate"
        )) else "EMPTY"
    )
    crypto_next = (
        "Crypto/RWA pack complete — review outputs/crypto_rwa/"
        if crypto_pack.get("pack_complete")
        else "Generate maps, evidence cards, and export Crypto/RWA pack."
    )

    module_cards = [
        _mod(
            "Jarvis Automation Hub",
            "logs/jarvis_tasks/proof_log.jsonl",
            "./scripts/jarvis_run_task.sh --list",
            "All automation registers on platform_main :8686 — launchd plists ship Disabled.",
            status="PASS" if (ROOT / "config" / "jarvis_automation.yaml").exists() else "MISSING",
            purpose="Task registry, proof logs, Aether read-only adapter, crypto scan dry-run.",
            module_href="/api/jarvis/tasks",
        ),
        _mod(
            "Private Local AI Nodes",
            "outputs/local_ai_node/pack_status.json",
            "./scripts/accept_local_ai_nodes.sh",
            pack_next,
            status=pack_label,
            purpose=(
                "Local AI capability deployment for private workflows. "
                "Generate pilot brief, package tier, checklist, timeline, and agent roles to disk."
            ),
            module_href="/ui/local-ai-nodes",
            pack_complete=pack_status.get("pack_complete", False),
        ),
        _mod(
            "Aether Nexus",
            "deliver/proof/jarvis/aether_snapshot_latest.json",
            "./scripts/jarvis_run_task.sh aether.snapshot.readonly --dry-run",
            "Start sidecar with ./aether_nexus/run_all.sh then open dashboard :8510.",
            status="PASS" if (ROOT / "aether_nexus" / "aether_dashboard.py").exists() else "MISSING",
            purpose=(
                "Options / equity dry-run scanner, IB paper daemon, Streamlit console. "
                "Jarvis reads JSON snapshots only — execution stays in the sidecar."
            ),
            module_href="/ui/trading",
        ),
        _mod(
            "Crypto / RWA Sovereignty",
            "outputs/crypto_rwa/crypto_rwa_pack_status.json",
            "./scripts/accept_crypto_rwa_functional.sh",
            crypto_next,
            status=crypto_pack_label,
            purpose=_CRYPTO_RWA_PURPOSE,
            rwa_sections=rwa_sections,
            agent_role=_CRYPTO_AGENT_ROLE,
            risk_boundaries=_CRYPTO_RISK_BOUNDARIES,
            evidence_count=len(evidence_cards),
            module_href="/ui/crypto",
            pack_complete=crypto_pack.get("pack_complete", False),
        ),
        _mod("Proof Pack", "deliver/proof_pack/ACCEPTANCE_REPORT.md",
             "./scripts/accept_proof_pack.sh", "Build template repo + scopegate before sales copy."),
        _mod("Senior", "deliver/proof/openclaw_v1/ACCEPTANCE_REPORT.md",
             "./scripts/accept_senior_v1.sh", "V1 hard gates verified locally."),
    ]

    return {
        "title": "Overview",
        "subtitle": "Sovereign ops console — 4-module local dashboard.",
        "page_kind": "overview",
        "system_verdict": sv,
        "system_verdict_tone": _status_tone(sv),
        "current_round": r,
        "next_action": bottleneck,
        "module_cards": module_cards,
        "cards": [],
        "sections": [],
        "side_panel": [],
    }


def _collect_audit_context() -> dict[str, Any]:
    review = _collect_review_artifact()
    return {
        "title": "Audit",
        "subtitle": "MUST_FIX / OPTIONAL and recent local audit lines.",
        "show_core_seg": True,
        "cards": [
            {"label": "Audit artifact", "value": review["status"], "tone": "ready" if "present" in review["status"].lower() else "blocked"},
            {"label": "Audit log", "value": "logs/audit.log", "tone": "neutral"},
            {"label": "Coordination", "value": "on", "tone": "ready"},
        ],
        "sections": [
            {"title": "MUST_FIX", "kind": "checklist", "items": [{"label": item, "status": "blocked"} for item in review["must_fix"]]},
            {"title": "OPTIONAL", "kind": "activity", "items": review["optional"]},
            {"title": "Latest Audit Lines", "kind": "activity", "items": _tail_lines(LOGS_DIR / "audit.log", 10)},
        ],
        "side_panel": [
            {"title": "Review Artifact", "kind": "paths", "items": [
                {"label": "Artifact", "value": "deliver/review/claude_review.json" if (DELIVER_DIR / "review" / "claude_review.json").exists() else "No saved review artifact"},
            ]},
            {"title": "Indicators", "kind": "chips", "items": ["coordination mode", "local-first", "external-off"]},
            {"title": "Current Proof", "kind": "paths", "items": [
                {"label": "Proof", "value": str((DELIVER_DIR / "proof" / "ACCEPTANCE_REPORT.md").relative_to(ROOT))},
            ]},
        ],
    }


def _collect_rounds_context() -> dict[str, Any]:
    rounds = _build_collaboration_rounds()
    latest = rounds[0]
    return {
        "title": "Archive & compare",
        "subtitle": "Past rounds, flow timeline, and proof paths.",
        "show_core_seg": True,
        "rounds": rounds,
        "acceptance_command": "./scripts/accept.sh",
        "recent_audit": _tail_lines(LOGS_DIR / "audit.log", 4),
        "selected_round": latest,
        "stage_panels": _round_stage_panels(latest),
        "shell_mode": "rounds",
    }


@app.get("/", response_class=HTMLResponse)
async def root_ui(request: Request):
    build_compiled_memory()
    return templates.TemplateResponse(request, "workspace.html", _collect_overview_context() | {"request": request})


@app.get("/ui/overview", response_class=HTMLResponse)
async def overview_ui(request: Request):
    build_compiled_memory()
    return templates.TemplateResponse(request, "workspace.html", _collect_overview_context() | {"request": request})


@app.get("/ui/desk", response_class=HTMLResponse)
async def desk_ui(request: Request):
    build_compiled_memory()
    return templates.TemplateResponse(request, "workbench.html", _collect_workbench_context() | {"request": request})


@app.get("/ui/workbench")
async def workbench_compat():
    return RedirectResponse(url="/ui/desk", status_code=307)


@app.get("/ui/archive", response_class=HTMLResponse)
async def archive_ui(request: Request):
    build_compiled_memory()
    return templates.TemplateResponse(request, "workbench.html", _collect_rounds_context() | {"request": request})


@app.get("/ui/workbench/rounds")
async def workbench_rounds_compat():
    return RedirectResponse(url="/ui/archive", status_code=307)


@app.get("/ui/rounds")
async def rounds_alias():
    return RedirectResponse(url="/ui/archive", status_code=307)


@app.get("/ui/audit", response_class=HTMLResponse)
async def audit_ui(request: Request):
    build_compiled_memory()
    return templates.TemplateResponse(request, "workspace.html", _collect_audit_context() | {"request": request})


@app.get("/ui/local-ai-nodes", response_class=HTMLResponse)
async def local_ai_nodes_ui(request: Request):
    build_compiled_memory()
    flash = request.query_params.get("ok", "")
    flash_file = request.query_params.get("file", "")
    flash_error = request.query_params.get("error", "")
    return templates.TemplateResponse(
        request,
        "workspace.html",
        _collect_local_ai_nodes_context(flash=flash, flash_file=flash_file, flash_error=flash_error)
        | {"request": request},
    )


def _local_ai_redirect(ok: str, rel_path: str) -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(
        url=f"/ui/local-ai-nodes?ok={quote(ok)}&file={quote(rel_path)}",
        status_code=303,
    )


def _save_intake_from_form(
    customer_type: str,
    current_device: str,
    target_use_case: str,
    privacy_sensitivity: str,
    desired_local_functions: str,
    budget_range: str,
) -> Intake:
    intake = _intake_from_form(
        customer_type=customer_type,
        current_device=current_device,
        target_use_case=target_use_case,
        privacy_sensitivity=privacy_sensitivity,
        desired_local_functions=desired_local_functions,
        budget_range=budget_range,
    )
    save_intake(intake)
    return intake


@app.post("/ui/local-ai-nodes/action/pilot-brief")
async def local_ai_pilot_brief(
    customer_type: str = Form(""),
    current_device: str = Form(""),
    target_use_case: str = Form(""),
    privacy_sensitivity: str = Form(""),
    desired_local_functions: str = Form(""),
    budget_range: str = Form(""),
):
    try:
        intake = _save_intake_from_form(
            customer_type, current_device, target_use_case,
            privacy_sensitivity, desired_local_functions, budget_range,
        )
        path = write_pilot_brief(intake)
        return _local_ai_redirect("pilot_brief", str(path.relative_to(ROOT)))
    except Exception as exc:
        return RedirectResponse(url=f"/ui/local-ai-nodes?error={exc}", status_code=303)


@app.post("/ui/local-ai-nodes/action/package-recommendation")
async def local_ai_package(
    customer_type: str = Form(""),
    current_device: str = Form(""),
    target_use_case: str = Form(""),
    privacy_sensitivity: str = Form(""),
    desired_local_functions: str = Form(""),
    budget_range: str = Form(""),
):
    try:
        intake = _save_intake_from_form(
            customer_type, current_device, target_use_case,
            privacy_sensitivity, desired_local_functions, budget_range,
        )
        path = write_package_recommendation(intake)
        return _local_ai_redirect("package_recommendation", str(path.relative_to(ROOT)))
    except Exception as exc:
        return RedirectResponse(url=f"/ui/local-ai-nodes?error={exc}", status_code=303)


@app.post("/ui/local-ai-nodes/action/delivery-checklist")
async def local_ai_checklist(
    customer_type: str = Form(""),
    current_device: str = Form(""),
    target_use_case: str = Form(""),
    privacy_sensitivity: str = Form(""),
    desired_local_functions: str = Form(""),
    budget_range: str = Form(""),
):
    try:
        intake = _save_intake_from_form(
            customer_type, current_device, target_use_case,
            privacy_sensitivity, desired_local_functions, budget_range,
        )
        path = write_delivery_checklist(intake)
        return _local_ai_redirect("delivery_checklist", str(path.relative_to(ROOT)))
    except Exception as exc:
        return RedirectResponse(url=f"/ui/local-ai-nodes?error={exc}", status_code=303)


@app.post("/ui/local-ai-nodes/action/delivery-timeline")
async def local_ai_timeline(
    customer_type: str = Form(""),
    current_device: str = Form(""),
    target_use_case: str = Form(""),
    privacy_sensitivity: str = Form(""),
    desired_local_functions: str = Form(""),
    budget_range: str = Form(""),
):
    try:
        intake = _save_intake_from_form(
            customer_type, current_device, target_use_case,
            privacy_sensitivity, desired_local_functions, budget_range,
        )
        path = write_delivery_timeline(intake)
        return _local_ai_redirect("delivery_timeline", str(path.relative_to(ROOT)))
    except Exception as exc:
        return RedirectResponse(url=f"/ui/local-ai-nodes?error={exc}", status_code=303)


@app.post("/ui/local-ai-nodes/action/agent-roles")
async def local_ai_roles(
    customer_type: str = Form(""),
    current_device: str = Form(""),
    target_use_case: str = Form(""),
    privacy_sensitivity: str = Form(""),
    desired_local_functions: str = Form(""),
    budget_range: str = Form(""),
):
    try:
        intake = _save_intake_from_form(
            customer_type, current_device, target_use_case,
            privacy_sensitivity, desired_local_functions, budget_range,
        )
        path = write_agent_roles(intake)
        return _local_ai_redirect("agent_roles", str(path.relative_to(ROOT)))
    except Exception as exc:
        return RedirectResponse(url=f"/ui/local-ai-nodes?error={exc}", status_code=303)


@app.post("/ui/local-ai-nodes/action/export-pack")
async def local_ai_export(
    customer_type: str = Form(""),
    current_device: str = Form(""),
    target_use_case: str = Form(""),
    privacy_sensitivity: str = Form(""),
    desired_local_functions: str = Form(""),
    budget_range: str = Form(""),
):
    try:
        intake = _save_intake_from_form(
            customer_type, current_device, target_use_case,
            privacy_sensitivity, desired_local_functions, budget_range,
        )
        export_full_pack(intake)
        return _local_ai_redirect("export_pack", "outputs/local_ai_node/")
    except Exception as exc:
        return RedirectResponse(url=f"/ui/local-ai-nodes?error={exc}", status_code=303)


@app.get("/ui/trading", response_class=HTMLResponse)
async def aether_nexus_ui(request: Request):
    """Jarvis trading entry — delegates to Aether Nexus sidecar (:8510)."""
    build_compiled_memory()
    return templates.TemplateResponse(
        request, "workspace.html", _collect_aether_nexus_context() | {"request": request}
    )


@app.get("/ui/crypto/onchain.json")
async def crypto_onchain_json() -> JSONResponse:
    return JSONResponse(_load_onchain_live())


@app.get("/ui/crypto", response_class=HTMLResponse)
async def crypto_ui(request: Request):
    build_compiled_memory()
    selected_tab = request.query_params.get("tab", "delivery")
    flash = request.query_params.get("ok", "")
    flash_file = request.query_params.get("file", "")
    flash_error = request.query_params.get("error", "")
    return templates.TemplateResponse(
        request,
        "workspace.html",
        _collect_crypto_context(selected_tab, flash=flash, flash_file=flash_file, flash_error=flash_error)
        | {"request": request},
    )


def _crypto_redirect(ok: str, rel_path: str) -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(url=f"/ui/crypto?ok={quote(ok)}&file={quote(rel_path)}", status_code=303)


def _crypto_context_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    registry = _load_crypto_rwa_registry()
    evidence_cards = _load_crypto_evidence_cards()
    return _enrich_crypto_rwa_sections(registry, evidence_cards), evidence_cards


def _save_crypto_intake_from_form(
    protocol_name: str,
    asset_name: str,
    use_case: str,
    focus_section: str,
) -> CryptoIntake:
    intake = CryptoIntake(
        protocol_name=protocol_name.strip(),
        asset_name=asset_name.strip(),
        use_case=use_case.strip(),
        focus_section=focus_section.strip() or "stablecoins",
    )
    save_crypto_intake(intake)
    return intake


@app.post("/ui/crypto/action/infrastructure-map")
async def crypto_action_infrastructure_map():
    try:
        sections, cards = _crypto_context_data()
        path = write_rwa_infrastructure_map(sections=sections, evidence_cards=cards)
        return _crypto_redirect("rwa_infrastructure_map", str(path.relative_to(ROOT)))
    except Exception as exc:
        return RedirectResponse(url=f"/ui/crypto?error={exc}", status_code=303)


@app.post("/ui/crypto/action/stablecoin-evidence")
async def crypto_action_stablecoin_evidence(
    protocol_name: str = Form(""),
    asset_name: str = Form(""),
    use_case: str = Form(""),
    focus_section: str = Form("stablecoins"),
):
    try:
        intake = _save_crypto_intake_from_form(protocol_name, asset_name, use_case, focus_section)
        _, cards = _crypto_context_data()
        path = write_stablecoin_evidence_card(intake, evidence_cards=cards)
        return _crypto_redirect("stablecoin_evidence_card", str(path.relative_to(ROOT)))
    except Exception as exc:
        return RedirectResponse(url=f"/ui/crypto?error={exc}", status_code=303)


@app.post("/ui/crypto/action/agent-payment-risk")
async def crypto_action_agent_payment_risk():
    try:
        path = write_agent_payment_risk_note()
        return _crypto_redirect("agent_payment_risk_note", str(path.relative_to(ROOT)))
    except Exception as exc:
        return RedirectResponse(url=f"/ui/crypto?error={exc}", status_code=303)


@app.post("/ui/crypto/action/proof-pack-candidate")
async def crypto_action_proof_pack_candidate():
    try:
        _, cards = _crypto_context_data()
        path = write_rwa_proof_pack_candidate(evidence_cards=cards)
        return _crypto_redirect("rwa_proof_pack_candidate", str(path.relative_to(ROOT)))
    except Exception as exc:
        return RedirectResponse(url=f"/ui/crypto?error={exc}", status_code=303)


@app.post("/ui/crypto/action/export-pack")
async def crypto_action_export_pack(
    protocol_name: str = Form(""),
    asset_name: str = Form(""),
    use_case: str = Form(""),
    focus_section: str = Form("stablecoins"),
):
    try:
        intake = _save_crypto_intake_from_form(protocol_name, asset_name, use_case, focus_section)
        sections, cards = _crypto_context_data()
        export_crypto_rwa_pack(intake, sections=sections, evidence_cards=cards)
        return _crypto_redirect("export_pack", "outputs/crypto_rwa/")
    except Exception as exc:
        return RedirectResponse(url=f"/ui/crypto?error={exc}", status_code=303)


@app.get("/ui/proof-pack", response_class=HTMLResponse)
async def proof_pack_ui(request: Request):
    build_compiled_memory()
    return templates.TemplateResponse(request, "workspace.html", _collect_proof_pack_context() | {"request": request})


@app.get("/ui/proofpack")
async def proofpack_compat():
    return RedirectResponse(url="/ui/proof", status_code=307)


@app.get("/ui/proof", response_class=HTMLResponse)
async def proof_ui(request: Request):
    build_compiled_memory()
    return templates.TemplateResponse(request, "workspace.html", _collect_proofpack_context() | {"request": request})


@app.get("/ui/senior", response_class=HTMLResponse)
async def senior_ui(request: Request):
    build_compiled_memory()
    return templates.TemplateResponse(request, "workspace.html", _collect_senior_v2_context() | {"request": request})


@app.get("/ui/senior_client")
async def senior_client_compat():
    return RedirectResponse(url="/ui/senior", status_code=307)


@app.post("/map_intent")
async def map_intent(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_input = str(payload.get("message", ""))
    context_history = load_compiled_context()
    mapped = mapper.map_intent(user_input, context_history)
    return mapped


@app.post("/transmit")
async def transmit_intent(payload: Dict[str, Any]) -> StreamingResponse:
    ast_data = payload.get("intent_map") if isinstance(payload.get("intent_map"), dict) else payload
    context_map = payload.get("context_map") if isinstance(payload.get("context_map"), dict) else {}
    context_map["compiled_memory"] = load_compiled_context()

    echo = ast_data.get("echo")
    if not echo:
        vector = ast_data.get("intent_vector") or ""
        echo = str(vector)

    messages = [
        {
            "role": "user",
            "content": echo,
        }
    ]

    existing_state = read_state()
    _ = existing_state
    ast_hash = ast_data.get("context_hash")
    if ast_hash is None:
        ast_hash = hash(str(ast_data))

    start = time.monotonic()
    write_state(ast_hash, 0.0)

    async def stream_tokens():
        count = 0
        async for token in ollama.stream_transmit(messages, context_map=context_map):
            count += len(token)
            yield token
        duration = time.monotonic() - start
        write_state(ast_hash, duration)
        log_grid_event(ast_hash=ast_hash, token_count=count)

    return StreamingResponse(
        stream_tokens(),
        media_type="text/plain; charset=utf-8",
        headers={"X-Accel-Buffering": "no"},
    )


@app.get("/router/compiled-memory")
async def router_compiled_memory() -> Dict[str, Any]:
    build_compiled_memory()
    return {
        "ok": True,
        "source": "knowledge/compiled/*.md",
        "preview": load_compiled_context()[:600],
    }


@app.post("/review/run")
async def run_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    spec_content = str(payload.get("spec_content", "")).strip()
    if not spec_content:
        raise HTTPException(status_code=400, detail="spec_content is required")
    pipeline = ReviewPipeline()
    result = pipeline.run(spec_content, skip_claude=bool(payload.get("skip_claude", False)))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "review pipeline blocked"))
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8686, log_level="info")

