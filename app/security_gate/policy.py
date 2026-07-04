from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from pathlib import Path
import yaml

DEFAULT_CONFIG_PATH = Path("config/security_gate.yaml")

@dataclass
class GateDecision:
    approved: bool
    reason: str

def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_policy(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    cfg = _load_yaml(config_path)

    # Hard defaults if missing
    cfg.setdefault("gate", {})
    cfg["gate"].setdefault("enabled", True)
    cfg["gate"].setdefault("require_human_confirm", True)

    cfg.setdefault("limits", {})
    cfg["limits"].setdefault("per_tx_usd_cap", 100)
    cfg["limits"].setdefault("daily_usd_cap", 300)

    cfg.setdefault("allowlist", {})
    cfg["allowlist"].setdefault("actions", ["sign_tx", "broadcast_tx", "withdraw_request"])
    cfg["allowlist"].setdefault("addresses", [])

    return cfg

def validate_request(req: Dict[str, Any], policy: Dict[str, Any]) -> GateDecision:
    if not policy.get("gate", {}).get("enabled", True):
        return GateDecision(False, "gate_disabled_by_policy")

    action = str(req.get("action", "")).strip()
    if not action:
        return GateDecision(False, "missing_action")

    allowed_actions: List[str] = policy.get("allowlist", {}).get("actions", [])
    if action not in allowed_actions:
        return GateDecision(False, f"action_not_allowlisted:{action}")

    # transfer-like checks: require address allowlist
    to_addr = (req.get("to_address") or "").strip()
    if action in ("sign_tx", "broadcast_tx", "withdraw_request") and to_addr:
        allowed_addrs: List[str] = policy.get("allowlist", {}).get("addresses", [])
        if not allowed_addrs:
            return GateDecision(False, "empty_address_allowlist")
        if to_addr not in allowed_addrs:
            return GateDecision(False, f"to_address_not_allowlisted:{to_addr}")

    # usd cap checks (best-effort; deny if exceeds)
    usd = req.get("usd_value")
    if usd is not None:
        try:
            usd_val = float(usd)
        except Exception:
            return GateDecision(False, "usd_value_not_numeric")

        per_tx_cap = float(policy.get("limits", {}).get("per_tx_usd_cap", 100))
        if usd_val > per_tx_cap:
            return GateDecision(False, f"per_tx_cap_exceeded:{usd_val}>{per_tx_cap}")

    # daily cap enforcement is V1 placeholder (we log; do not maintain state here)
    return GateDecision(True, "policy_ok")
