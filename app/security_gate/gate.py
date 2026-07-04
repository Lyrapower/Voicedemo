from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.security_gate.policy import GateDecision, load_policy, validate_request

LOG_PATH = Path("logs/security_gate.log")

def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def ensure_log_dir():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def log_decision(req: Dict[str, Any], decision: GateDecision, human_confirmed: bool):
    ensure_log_dir()
    entry = {
        "ts": _utc_iso(),
        "action": req.get("action"),
        "to_address": req.get("to_address"),
        "usd_value": req.get("usd_value"),
        "approved": decision.approved and human_confirmed,
        "policy_reason": decision.reason,
        "human_confirmed": human_confirmed,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def evaluate(req: Dict[str, Any], config_path: Optional[Path] = None, interactive: bool = True) -> Dict[str, Any]:
    policy = load_policy(config_path or Path("config/security_gate.yaml"))
    decision = validate_request(req, policy)

    require_confirm = bool(policy.get("gate", {}).get("require_human_confirm", True))
    human_confirmed = True

    # By default require human confirm for asset-moving actions
    if decision.approved and require_confirm and interactive:
        print("=== SECURITY GATE: HUMAN CONFIRM REQUIRED ===")
        print(f"Action: {req.get('action')}")
        print(f"To: {req.get('to_address')}")
        print(f"USD: {req.get('usd_value')}")
        ans = input("Approve? type YES to approve: ").strip()
        human_confirmed = (ans == "YES")

    # If not interactive, treat as NOT confirmed (including when policy already denied)
    if require_confirm and not interactive:
        human_confirmed = False

    log_decision(req, decision, human_confirmed)

    approved = bool(decision.approved and human_confirmed)
    return {
        "approved": approved,
        "policy_reason": decision.reason,
        "human_confirmed": human_confirmed,
        "log_path": str(LOG_PATH),
    }
