"""x402 policy only. Zero network, zero wallet, zero new dependencies."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.harness.action_envelope import ActionEnvelope
from app.harness.provenance import record_action, read_events
from app.harness.resource_gate import gate as resource_gate

PT = ZoneInfo("America/Los_Angeles")


@dataclass
class X402Config:
    daily_limit: float = 0.0
    per_tx_limit: float = 0.0
    payees: tuple[str, ...] = ()
    agents: dict[str, dict[str, float]] = field(default_factory=dict)


def load_x402_config(raw: dict[str, Any] | None = None) -> X402Config:
    raw = dict(raw or {})
    agents = {}
    for name, blk in (raw.get("agents") or {}).items():
        if isinstance(blk, dict):
            agents[str(name)] = {
                "daily_limit": float(blk.get("daily_limit") or blk.get("daily") or 0),
                "per_tx_limit": float(blk.get("per_tx_limit") or blk.get("per_tx") or 0),
            }
    return X402Config(
        daily_limit=float(raw.get("daily_limit") or 0),
        per_tx_limit=float(raw.get("per_tx_limit") or 0),
        payees=tuple(str(p) for p in (raw.get("payees") or [])),
        agents=agents,
    )


_SPENT: dict[tuple[str, str], float] = {}


def _day() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d")


def _limits(cfg: X402Config, agent: str) -> tuple[float, float]:
    ov = cfg.agents.get(agent) or {}
    daily = float(ov.get("daily_limit", cfg.daily_limit))
    per_tx = float(ov.get("per_tx_limit", cfg.per_tx_limit))
    return daily, per_tx


def authorize(
    agent: str,
    amount: float,
    payee: str,
    mission: str,
    action: str,
    *,
    cfg: X402Config | None = None,
    authorization_token: str | None = None,
    surface: dict[str, Any] | None = None,
) -> dict[str, str]:
    """ALLOW/DENY + reason. Writes provenance. No chain or HTTP."""
    cfg = cfg or X402Config()
    env = ActionEnvelope(
        mission_id=str(mission),
        action_id=str(action),
        decision_origin="USER",
        selected_resource="x402",
        operation="authorize",
        arguments={"agent": agent, "amount": amount, "payee": payee},
        authorization_scope="money_moving",
    )
    record_action(env)
    daily, per_tx = _limits(cfg, agent)
    if daily <= 0 or per_tx <= 0:
        return _deny(env, "default_zero", authorization_token, surface)
    if amount > per_tx:
        return _deny(env, "per_tx_cap", authorization_token, surface)
    if cfg.payees and payee not in cfg.payees:
        return _deny(env, "payee_not_whitelisted", authorization_token, surface)
    if not cfg.payees:
        return _deny(env, "payee_not_whitelisted", authorization_token, surface)
    spent = _SPENT.get((agent, _day()), 0.0)
    if spent + amount > daily:
        return _deny(env, "daily_cap", authorization_token, surface)
    gd = resource_gate(env, authorization_token=authorization_token, surface=surface or _surface())
    if not gd.allowed:
        reason = "no_human_token" if "token" in gd.reason else gd.reason
        return {"decision": "DENY", "reason": reason}
    _SPENT[(agent, _day())] = spent + amount
    return {"decision": "ALLOW", "reason": "ok"}


def _surface() -> dict[str, Any]:
    return {"capabilities": [
        {"capability_id": "x402", "status": "declared", "permission": "money_moving", "kind": "policy"},
    ], "model_profiles": []}


def _deny(env: ActionEnvelope, reason: str, token: str | None, surface: dict | None) -> dict[str, str]:
    resource_gate(env, authorization_token=token, surface=surface or _surface())
    return {"decision": "DENY", "reason": reason}


def reset_spent() -> None:
    _SPENT.clear()
