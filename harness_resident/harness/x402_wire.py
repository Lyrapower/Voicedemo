"""v6 x402 adapters. Gate fail-closes unless a full-field grant exists.

Existing resource_gate only binds token to mission:action. v6 requires
agent/amount_units/currency/payee/mission/action/request_id. There is no
trusted grant store for those extra fields, so this adapter never returns
True in production. Tests inject their own gate.
"""
from __future__ import annotations

from pathlib import Path

from harness.x402_policy import Policy, X402Policy

STATE_PATH = Path(__file__).resolve().parents[1] / "state" / "x402_policy_v6.sqlite"


def resource_gate_adapter(token, context):
    if not isinstance(context, dict):
        return False
    need = ("agent", "amount_units", "currency", "payee", "mission", "action", "request_id")
    if any(k not in context for k in need):
        return False
    if not token:
        return False
    # Intentionally not True: no full-field authorization record exists.
    return False


class ProvenanceAdapter:
    def record_action(self, event_id=None, **event):
        # Local ActionEnvelope write is not a harness-shared durable ACK.
        # Strict True would mark the outbox synced. Keep pending.
        return None


def make_policy() -> Policy:
    # Keep approved empty caps / empty whitelist. Do not invent payees or funds.
    return Policy(daily_cap={}, per_tx_cap={}, payee_whitelist=set())


def make_x402() -> X402Policy:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return X402Policy(
        make_policy(),
        gate=resource_gate_adapter,
        state_path=str(STATE_PATH),
        provenance=ProvenanceAdapter(),
    )
