"""Reality-facing action/receipt contract.

The Harness transports and enforces. It does not provide next-action cognition.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

FORBIDDEN_RECEIPT_FIELDS = {
    "recommended_action", "suggested_fix", "next_worker", "next_tool",
    "fallback", "strategy", "reasoning", "hypothesis",
}
# Fable review 2026-08-26: exact-name set was trivially bypassed ({"next_step": "buy more"} passed). Prefix classes:
FORBIDDEN_RECEIPT_PREFIXES = ("next_", "recommend", "suggest", "should_", "plan", "advice", "fallback", "strategy")
VALID_RECEIPT_STATUS = {"CLAIMED", "EXECUTED", "FAILED", "DENIED", "VERIFIED", "FAILED_VERIFICATION", "TIMEOUT"}


def _leaks(keys) -> list[str]:
    out = []
    for k in keys:
        kl = str(k).lower()
        if k in FORBIDDEN_RECEIPT_FIELDS or any(kl.startswith(p) for p in FORBIDDEN_RECEIPT_PREFIXES):
            out.append(str(k))
    return sorted(out)

VALID_DECISION_ORIGINS = {
    "GRID_LOCAL", "GRID_DELEGATED_GLM", "HARNESS", "VERIFIER", "TOOL", "USER"
}


@dataclass(frozen=True)
class ActionEnvelope:
    mission_id: str
    action_id: str
    decision_origin: str
    selected_resource: str
    operation: str
    arguments: dict[str, Any] = field(default_factory=dict)
    authorization_scope: str = "read_only"
    expected_effect: str = ""
    timestamp: str = ""

    def validate(self) -> None:
        if self.decision_origin not in VALID_DECISION_ORIGINS:
            raise ValueError(f"invalid decision_origin: {self.decision_origin}")
        if self.decision_origin in {"HARNESS", "VERIFIER", "TOOL"}:
            raise ValueError("next cognitive action cannot originate from Harness/Verifier/Tool")
        if not self.selected_resource or not self.operation:
            raise ValueError("selected_resource and operation are required")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        from app.harness import provenance
        if not getattr(provenance, "_RECORDING", False):
            provenance.record_action(self)
        return asdict(self)


@dataclass(frozen=True)
class FactualReceipt:
    mission_id: str
    action_id: str
    status: str
    executed: bool
    result: Any = None
    error: str = ""
    evidence_pointer: str = ""
    receipt_hash: str = ""
    observed_value: Any = None
    remaining_budget: Any = None
    escalation_state: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.status not in VALID_RECEIPT_STATUS:
            raise ValueError(f"invalid receipt status: {self.status}")
        leaked = _leaks(payload)
        if leaked:
            raise ValueError(f"cognitive leakage in receipt: {leaked}")
        leaked_meta = _leaks(self.metadata or {})
        if leaked_meta:
            raise ValueError(f"cognitive leakage in receipt metadata: {leaked_meta}")
        from app.harness import provenance
        if not getattr(provenance, "_RECORDING", False):
            provenance.record_receipt(self)
        return payload


def validate_external_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    leaked = _leaks(payload)
    if leaked:
        raise ValueError(f"receipt contains forbidden cognition fields: {leaked}")
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, dict):
        leaked_meta = _leaks(metadata)
        if leaked_meta:
            raise ValueError(f"receipt metadata contains forbidden cognition fields: {leaked_meta}")
    if payload.get("status") == "VERIFIED" and not (metadata.get("verifier_predicate") if isinstance(metadata, dict) else None):
        raise ValueError("external receipt claims VERIFIED without verifier predicate")
    return payload
