"""x402 策略层:只判 ALLOW/DENY,不付款,不出网,不依赖第三方库。
PKG v5 核心 + 接线:provenance → record_action, gate → resource_gate。"""
from __future__ import annotations
import hashlib, json, time
from dataclasses import dataclass, field
from typing import Any

from app.harness.action_envelope import ActionEnvelope
from app.harness.provenance import record_action
from app.harness.resource_gate import gate as resource_gate


@dataclass
class Policy:
    daily_cap: dict = field(default_factory=dict)
    per_tx_cap: dict = field(default_factory=dict)
    payee_whitelist: set = field(default_factory=set)
    day_key: callable = lambda: time.strftime("%Y-%m-%d")


class MemProvenance:
    """默认记录器;现场替换为 provenance.record_action。hash 链保证可回放。"""
    def __init__(self): self.chain=[]
    def record_action(self, **ev):
        prev = self.chain[-1]["hash"] if self.chain else "0"*64
        body = json.dumps({**ev, "prev": prev}, sort_keys=True)
        self.chain.append({**ev, "prev": prev, "hash": hashlib.sha256(body.encode()).hexdigest()})
    def verify(self):
        prev="0"*64
        for e in self.chain:
            body=json.dumps({k:v for k,v in e.items() if k!="hash"}, sort_keys=True)
            if e["prev"]!=prev or hashlib.sha256(body.encode()).hexdigest()!=e["hash"]: return False
            prev=e["hash"]
        return True


class RecordActionProvenance:
    """PKG v5 接线:Mem 链 + 现有 record_action(ActionEnvelope)。"""
    def __init__(self):
        self.mem = MemProvenance()
        self.chain = self.mem.chain
    def record_action(self, **ev):
        self.mem.record_action(**ev)
        env = ActionEnvelope(
            mission_id=str(ev.get("mission") or "x402"),
            action_id=str(ev.get("action") or "authorize"),
            decision_origin="USER",
            selected_resource="x402",
            operation="authorize",
            arguments={k: ev.get(k) for k in ("agent", "amount", "payee", "verdict", "reason")},
            authorization_scope="money_moving",
        )
        record_action(env)
    def verify(self):
        return self.mem.verify()


class X402Policy:
    def __init__(self, policy: Policy, provenance=None, gate=None):
        self.p=policy; self.prov=provenance or MemProvenance(); self.gate=gate
        self.spent={}

    def authorize(self, agent, amount, payee, mission, action, human_token=None):
        reason=None
        if human_token is None: reason="no_human_token"
        elif self.gate and not self.gate(human_token, f"{mission}:{action}"): reason="token_not_bound"
        elif amount<=0: reason="bad_amount"
        elif payee not in self.p.payee_whitelist: reason="payee_not_whitelisted"
        elif amount>self.p.per_tx_cap.get(agent,0): reason="per_tx_cap"
        else:
            k=(agent,self.p.day_key())
            if self.spent.get(k,0)+amount>self.p.daily_cap.get(agent,0): reason="daily_cap"
        verdict="DENY" if reason else "ALLOW"
        if verdict=="ALLOW":
            k=(agent,self.p.day_key()); self.spent[k]=self.spent.get(k,0)+amount
        self.prov.record_action(kind="x402_authorize", agent=agent, amount=amount, payee=payee,
                                mission=mission, action=action, verdict=verdict, reason=reason or "ok")
        return verdict, reason or "ok"


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


def _surface() -> dict[str, Any]:
    return {"capabilities": [
        {"capability_id": "x402", "status": "declared", "permission": "money_moving", "kind": "policy"},
    ], "model_profiles": []}


def bound_gate(token, binding, surface=None):
    mission, _, action = binding.partition(":")
    env = ActionEnvelope(
        mission_id=mission, action_id=action, decision_origin="USER",
        selected_resource="x402", operation="authorize",
        authorization_scope="money_moving",
    )
    return resource_gate(env, authorization_token=token, surface=surface or _surface()).allowed


def _limits(cfg: X402Config, agent: str) -> tuple[float, float]:
    ov = cfg.agents.get(agent) or {}
    daily = float(ov.get("daily_limit", cfg.daily_limit))
    per_tx = float(ov.get("per_tx_limit", cfg.per_tx_limit))
    return daily, per_tx


_WIRED: X402Policy | None = None


def reset_spent() -> None:
    global _WIRED
    _WIRED = None


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
    """ALLOW/DENY + reason. PKG 类 + record_action + resource_gate。"""
    global _WIRED
    cfg = cfg or X402Config()
    daily, per_tx = _limits(cfg, agent)
    if _WIRED is None:
        _WIRED = X402Policy(
            Policy(daily_cap={}, per_tx_cap={}, payee_whitelist=set()),
            provenance=RecordActionProvenance(),
            gate=lambda t, b: bound_gate(t, b, surface),
        )
    _WIRED.p.daily_cap[agent] = daily
    _WIRED.p.per_tx_cap[agent] = per_tx
    _WIRED.p.payee_whitelist = set(cfg.payees)
    verdict, reason = _WIRED.authorize(agent, amount, payee, mission, action, authorization_token)
    return {"decision": verdict, "reason": reason}
