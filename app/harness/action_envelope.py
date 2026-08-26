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
        leaked = FORBIDDEN_RECEIPT_FIELDS.intersection(payload)
        if leaked:
            raise ValueError(f"cognitive leakage in receipt: {sorted(leaked)}")
        if FORBIDDEN_RECEIPT_FIELDS.intersection(self.metadata):
            raise ValueError("cognitive leakage in receipt metadata")
        return payload


def validate_external_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    leaked = FORBIDDEN_RECEIPT_FIELDS.intersection(payload)
    if leaked:
        raise ValueError(f"receipt contains forbidden cognition fields: {sorted(leaked)}")
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, dict):
        leaked_meta = FORBIDDEN_RECEIPT_FIELDS.intersection(metadata)
        if leaked_meta:
            raise ValueError(f"receipt metadata contains forbidden cognition fields: {sorted(leaked_meta)}")
    return payload
