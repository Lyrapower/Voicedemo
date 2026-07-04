from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
BOTTLENECK_LEDGER_HEADER = "## Bottleneck Ledger (Top 3)"
TRADING_PERMISSION_LINE = "- trading_permission: allowed_only_if_active_constraint=yes"

# Core + satellite + hedge + backups (proxies must be subset).
_ALLOWED_TICKERS = frozenset(
    {"NVDA", "TSLA", "PLTR", "COIN", "CORZ", "BE", "SQQQ", "GLD", "AMD", "MU", "XLE"}
)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_bottleneck_ledger_section(timestamp_utc: str | None = None) -> str:
    """
    Fixed ledger format: max 3 rows, L0 > L1 > L2.
    Compile defaults: no live feed → activation_signals not market-specific → state dormant, confidence low.
    """
    ts = timestamp_utc or _utc_iso_now()
    entries: list[dict[str, object]] = [
        {
            "constraint_id": "POWER_DC",
            "constraint_layer": "L0",
            "state": "dormant",
            "confidence": "low",
            "proxies": "BE, XLE",
            "why_inevitable": "Scaling AI compute tightens power, grid, and permitting before GPU supply becomes the only binding constraint.",
            "activation_signals": [
                "type_news: no_multi_source_headline_cluster_in_local_ingest",
                "type_capex_flow: no_datacenter_power_capex_shift_signal_in_ingest",
            ],
            "notes": ["Compile defaults only; warming needs cross-type confirmation per transition rules."],
        },
        {
            "constraint_id": "DC_CAPACITY",
            "constraint_layer": "L1",
            "state": "dormant",
            "confidence": "low",
            "proxies": "CORZ",
            "why_inevitable": "Capacity and site timelines for compute real estate lag demand once power and interconnect bind.",
            "activation_signals": [
                "type_news: no_project_delay_attributed_to_power_or_permit_in_ingest",
                "type_rs: no_proxy_relative_strength_series_evaluated",
            ],
            "notes": ["No RS feed in this build; active requires strong signal or RS per rules."],
        },
        {
            "constraint_id": "GOV_AI_INFRA",
            "constraint_layer": "L2",
            "state": "dormant",
            "confidence": "low",
            "proxies": "PLTR",
            "why_inevitable": "Defense and government AI procurement paths gate durable infra spend separate from consumer tech cycles.",
            "activation_signals": [
                "type_policy: no_program_award_or_budget_line_cluster_in_ingest",
                "type_flow: no_PLTR_relative_strength_vs_basket_evaluated",
            ],
            "notes": [],
        },
    ]
    blocks: list[str] = []
    for raw in entries:
        e = dict(raw)
        proxies_raw = str(e["proxies"])
        tickers = {p.strip() for p in proxies_raw.replace(",", " ").split() if p.strip()}
        if not tickers <= _ALLOWED_TICKERS:
            e["state"] = "dormant"
        sigs = list(e["activation_signals"])[:4]
        if len(sigs) < 2:
            e["state"] = "dormant"
        lines = [
            f"- constraint_id: {e['constraint_id']}",
            f"- constraint_layer: {e['constraint_layer']}",
            f"- state: {e['state']}",
            f"- confidence: {e.get('confidence') or 'low'}",
            f"- proxies: {e['proxies']}",
            f"- why_inevitable: {e['why_inevitable']}",
            "- activation_signals:",
        ]
        for sig in sigs:
            lines.append(f"  - {sig}")
        lines.append(f"- last_update_utc: {ts}")
        notes = (e.get("notes") or [])[:2]
        if notes:
            lines.append("- notes:")
            for n in notes:
                lines.append(f"  - {n}")
        blocks.append("\n".join(lines))
    body = "\n\n".join(blocks)
    return f"{BOTTLENECK_LEDGER_HEADER}\n\n{body}"
COMPILED_DIR = ROOT / "knowledge" / "compiled"
PROOF_DIR = ROOT / "deliver" / "proof"


@dataclass
class ModuleSnapshot:
    name: str
    state: str
    proof: str
    blockers: list[str]
    next_actions: list[str]
    locked_rules: list[str]


def _report_verdict(path: Path) -> str:
    if not path.exists():
        return "UNKNOWN"
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "FINAL VERDICT: PASS" in text:
        return "PASS"
    if "FINAL VERDICT: FAIL" in text:
        return "FAIL"
    return "UNKNOWN"


def _existing_blockers(paths: Iterable[Path]) -> list[str]:
    blockers = []
    for path in paths:
        if not path.exists():
            blockers.append(f"missing: {path.relative_to(ROOT)}")
    return blockers or ["none"]


def _write_compiled_file(path: Path, title: str, snapshot: ModuleSnapshot) -> None:
    lines = [
        f"# {title}",
        "",
        "## Active Constraints",
        *[f"- {rule}" for rule in snapshot.locked_rules],
        "",
        "## Active Module State",
        f"- {snapshot.state}",
        "",
        "## Latest Proof / Acceptance Status",
        f"- {snapshot.proof}",
        "",
        "## Blockers",
        *[f"- {item}" for item in snapshot.blockers],
        "",
        "## Current Next Actions",
        *[f"- {item}" for item in snapshot.next_actions[:3]],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_trading_workspace(path: Path, title: str, snapshot: ModuleSnapshot) -> None:
    ts = _utc_iso_now()
    ledger = format_bottleneck_ledger_section(ts)
    lines = [
        f"# {title}",
        "",
        "## Active Constraints",
        *[f"- {rule}" for rule in snapshot.locked_rules],
        "",
        "## Active Module State",
        f"- {snapshot.state}",
        "",
        "## Latest Proof / Acceptance Status",
        f"- {snapshot.proof}",
        "",
        "## Blockers",
        *[f"- {item}" for item in snapshot.blockers],
        "",
        "## Current Next Actions",
        *[f"- {item}" for item in snapshot.next_actions[:3]],
        "",
        ledger,
        "",
        TRADING_PERMISSION_LINE,
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_compiled_memory() -> list[Path]:
    senior_report = PROOF_DIR / "openclaw_v1" / "ACCEPTANCE_REPORT.md"
    trading_report = PROOF_DIR / "trading" / "ACCEPTANCE_REPORT.md"
    crypto_report = PROOF_DIR / "crypto" / "ACCEPTANCE_REPORT.md"
    top_report = PROOF_DIR / "ACCEPTANCE_REPORT.md"

    senior_required = [
        ROOT / "clients" / "openclaw_senior_flutter" / "lib" / "features" / "home" / "home_page.dart",
        ROOT / "clients" / "openclaw_senior_flutter" / "lib" / "core" / "services" / "verified_mode_service.dart",
        ROOT / "clients" / "openclaw_senior_flutter" / "lib" / "core" / "services" / "safety_chain_service.dart",
    ]
    trading_required = [
        ROOT / "specs" / "trading_module_spec.md",
    ]
    crypto_required = [
        ROOT / "deliver" / "sow" / "CLIENT_SOW_TEMPLATE.md",
        ROOT / "deliver" / "deploy" / "DEPLOY_CHECKLIST.md",
        ROOT / "scripts" / "deploy_to_client_aws.sh",
    ]

    senior = ModuleSnapshot(
        name="senior",
        state="OpenClaw Senior V1 local-first UI and safety flow only.",
        proof=f"OpenClaw acceptance: {_report_verdict(senior_report)}",
        blockers=_existing_blockers(senior_required),
        next_actions=[
            "Keep urgent-first hierarchy stable.",
            "Keep external notifications off by default.",
            "Preserve proof and local log export path.",
        ],
        locked_rules=[
            "Presence Echo loop is real.",
            "Verified Mode hard gate is real.",
            "48/60/72h chain is real.",
            "No fake family notification claims.",
            "No camera OCR beyond placeholder.",
        ],
    )
    trading = ModuleSnapshot(
        name="trading",
        state="Trading shell stays deterministic and PASS-first.",
        proof=f"Trading acceptance: {_report_verdict(trading_report)}",
        blockers=_existing_blockers(trading_required),
        next_actions=[
            "Keep weekly cap at 3 including hedges.",
            "Keep satellite separate from fallback logic.",
            "Keep output human-readable and deterministic.",
        ],
        locked_rules=[
            "Core: NVDA, TSLA",
            "Satellite: PLTR, COIN, CORZ, BE",
            "Hedge: SQQQ, GLD",
            "Backups: AMD, MU, XLE",
            "No setup means PASS.",
            "Bottleneck ledger: L0 BE/XLE, L1 CORZ, L2 PLTR; trading_permission hook at file end.",
        ],
    )
    crypto = ModuleSnapshot(
        name="crypto",
        state="Crypto V1 stays probationary and external-off by default.",
        proof=f"Crypto acceptance: {_report_verdict(crypto_report)}",
        blockers=_existing_blockers(crypto_required),
        next_actions=[
            "Keep deploy artifacts concrete.",
            "Keep deploy script dry-run by default.",
            "Do not activate external services in this step.",
        ],
        locked_rules=[
            "Probationary side branch.",
            "Not autonomous by default.",
            "Client deliverables are mandatory.",
        ],
    )
    infra = ModuleSnapshot(
        name="infra",
        state="Jarvis routing layer stays local-first with compiled-memory-only read path.",
        proof=f"Top-level proof: {_report_verdict(top_report)}",
        blockers=_existing_blockers(
            [
                ROOT / "knowledge" / "source" / "ASTER.md",
                ROOT / "config" / "routing_policy.yaml",
                ROOT / "budgets.yaml",
                ROOT / "scripts" / "compile_memory.sh",
                ROOT / "scripts" / "compile_memory.py",
            ]
        ),
        next_actions=[
            "Compile memory on start.",
            "Block external adapters when disabled or kill-switched.",
            "Keep raw chat and raw logs out of router context.",
        ],
        locked_rules=[
            "external_enabled remains false by default.",
            "KILL_EXTERNAL blocks all external calls.",
            "Only knowledge/compiled/*.md feeds the local router context.",
        ],
    )

    written = []
    _write_compiled_file(COMPILED_DIR / "WORKSPACE_senior.md", "WORKSPACE Senior", senior)
    written.append(COMPILED_DIR / "WORKSPACE_senior.md")
    _write_trading_workspace(COMPILED_DIR / "WORKSPACE_trading.md", "WORKSPACE Trading", trading)
    written.append(COMPILED_DIR / "WORKSPACE_trading.md")
    _write_compiled_file(COMPILED_DIR / "WORKSPACE_crypto.md", "WORKSPACE Crypto", crypto)
    written.append(COMPILED_DIR / "WORKSPACE_crypto.md")
    _write_compiled_file(COMPILED_DIR / "WORKSPACE_infra.md", "WORKSPACE Infra", infra)
    written.append(COMPILED_DIR / "WORKSPACE_infra.md")

    memory_lines = [
        "# MEMORY",
        "",
        "## Active Constraints",
        "- Local-first behavior only.",
        "- External adapters remain OFF by default.",
        "- Router/Qwen may read only compiled memory artifacts.",
        "- No raw transcript dumping.",
        "",
        "## Active Module States",
        f"- OpenClaw Senior: {_report_verdict(senior_report)}",
        f"- Trading: {_report_verdict(trading_report)}",
        f"- Crypto: {_report_verdict(crypto_report)}",
        "",
        "## Latest Proof / Acceptance Status",
        f"- Top-level acceptance: {_report_verdict(top_report)}",
        "",
        "## Blockers",
        "- none" if all(_report_verdict(p) != "FAIL" for p in [senior_report, trading_report]) else "- see workspace files",
        "",
        "## Current Next Actions",
        "- Keep Step 3 acceptance green.",
        "- Keep routing layer external-off and dry-run only.",
        "- Keep compiled memory synced through scripts/compile_memory.sh.",
        "",
        "## Locked Rules",
        "- Do not feed raw logs to the router context.",
        "- Do not feed raw chat transcripts to the router context.",
        "- Keep next actions capped at 3 in compiled memory artifacts.",
    ]
    memory_path = COMPILED_DIR / "MEMORY.md"
    memory_path.write_text("\n".join(memory_lines) + "\n", encoding="utf-8")
    written.insert(0, memory_path)
    return written


def load_compiled_context() -> str:
    build_compiled_memory()
    chunks = []
    for path in sorted(COMPILED_DIR.glob("*.md")):
        chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n\n".join(chunks)


if __name__ == "__main__":
    for path in build_compiled_memory():
        print(path.relative_to(ROOT))
