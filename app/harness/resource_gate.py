"""Resource gate — deny without substitution. (Fable review 2026-08-26, fills Acceptance C/D/L)

The bundle's ActionEnvelope accepted any `selected_resource` string and any `authorization_scope`
(probe: selected_resource="bybit_live_perps", authorization_scope="money_moving" → accepted).
This module is the enforcement the docs promised but no file implemented:

- resource must exist in the capability surface (static or legacy) and be available;
- money-moving scopes require an explicit, non-empty human authorization token bound to (mission, action);
- venues on the jurisdiction blocklist are denied for the configured jurisdiction (US default);
- denial returns a FactualReceipt(status="DENIED") — never a substitute resource, never advice.

No network, no cognition, no fallback.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.harness.action_envelope import ActionEnvelope, FactualReceipt
from app.harness.capability_registry import capability_surface

MONEY_MOVING_SCOPES = {"money_moving", "live_trade", "wallet_send", "broker_order"}

# Jurisdiction policy is data, not opinion: venues that block or prohibit US persons for the listed products.
# Sources (2026-08): Coinbase Base App perps via Hyperliquid — "not available in the U.S., UK, Canada" (Coinbase, 2026-08-19);
# Hyperliquid front end prohibits U.S. persons (HL contributor CFTC filing, 2025); Bybit/Binance block US IPs
# (the bundle's own crypto_feed.py BLOCKED_US). Regulated US perps: CFTC-approved Kalshi BTC perps, Coinbase
# Derivatives (CDE) 24/7 cash-settled perpetual-style futures, Coinbase Financial Markets (FCM, institutional).
JURISDICTION_POLICY: dict[str, dict[str, Any]] = {
    "US": {
        "deny_venues": {"bybit", "binance", "hyperliquid", "okx", "mexc", "bitget", "gate"},
        "deny_products_on_denied_venues": {"perp", "swap", "futures", "margin"},
        "allow_venues": {"coinbase", "coinbase_derivatives", "coinbase_financial_markets", "kraken", "kalshi", "cme"},
    }
}


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    receipt: FactualReceipt | None = None


def _available_resources(surface: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    surface = surface or capability_surface()
    out: dict[str, dict[str, Any]] = {}
    for c in surface.get("capabilities", []):
        if not isinstance(c, dict) or "capability_id" not in c:
            continue
        out[c["capability_id"]] = c
        # provider names are also addressable resources (e.g. "aether_paper")
        prov = c.get("provider")
        if prov:
            out.setdefault(prov, c)
    for p in surface.get("model_profiles", []):
        if isinstance(p, dict) and p.get("node_id"):
            out[p["node_id"]] = {"capability_id": p["node_id"], "status": "declared", "permission": "model", "kind": "model"}
    return out


def _venue_of(resource: str, arguments: dict[str, Any]) -> str:
    v = str(arguments.get("venue") or arguments.get("exchange") or "").lower()
    if v:
        return v
    r = resource.lower()
    for name in ("bybit", "binance", "hyperliquid", "okx", "coinbase", "kraken", "kalshi", "cme"):
        if name in r:
            return name
    return ""


def gate(envelope: ActionEnvelope, *, jurisdiction: str | None = None,
         authorization_token: str | None = None, surface: dict[str, Any] | None = None) -> GateDecision:
    """Return allowed=True only when every predicate holds. Denials carry a factual receipt and no substitute."""
    envelope.validate()
    from app.harness import provenance
    provenance.record_action(envelope)
    jur = (jurisdiction or os.getenv("HARNESS_JURISDICTION", "US")).upper()
    resources = _available_resources(surface)
    res = resources.get(envelope.selected_resource)

    def deny(reason: str) -> GateDecision:
        rc = FactualReceipt(mission_id=envelope.mission_id, action_id=envelope.action_id, status="DENIED",
                            executed=False, error=reason,
                            metadata={"selected_resource": envelope.selected_resource, "substitute": None, "jurisdiction": jur})
        from app.harness import provenance
        provenance.record_receipt(rc)
        return GateDecision(False, reason, rc)

    if res is None:
        return deny("resource not in capability surface: %s" % envelope.selected_resource)
    if str(res.get("status", "")) in ("unavailable", "disabled"):
        return deny("resource %s status=%s" % (envelope.selected_resource, res.get("status")))
    perm = str(res.get("permission", "read_only"))
    scope = str(envelope.authorization_scope or "read_only")
    if scope in MONEY_MOVING_SCOPES:
        if perm in ("read_only", "paper_only", "local_write", "media_scoped", "loopback", "model"):
            return deny("scope %s exceeds resource permission %s" % (scope, perm))
        if not authorization_token or len(authorization_token) < 16:
            return deny("money-moving scope without explicit human authorization token")
        if not authorization_token.startswith("%s:%s:" % (envelope.mission_id, envelope.action_id)):
            return deny("authorization token not bound to this mission/action")
    policy = JURISDICTION_POLICY.get(jur, {})
    venue = _venue_of(envelope.selected_resource, envelope.arguments or {})
    product = str((envelope.arguments or {}).get("product") or envelope.operation or "").lower()
    if venue and venue in policy.get("deny_venues", set()):
        if any(p in product for p in policy.get("deny_products_on_denied_venues", set())) or scope in MONEY_MOVING_SCOPES:
            return deny("venue %s is not available to %s persons for %s" % (venue, jur, product or scope))
    return GateDecision(True, "ok", None)


def validate_capability_surface(surface: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stamp capability_id on every row (P4) and return the surface as exported.

    Does not substitute resources. Unavailable rows stay unavailable.
    """
    surface = dict(surface if surface is not None else capability_surface())
    caps = []
    for i, c in enumerate(surface.get("capabilities") or []):
        if not isinstance(c, dict):
            continue
        row = dict(c)
        if not row.get("capability_id"):
            src = str(row.get("source") or "legacy.unavailable")
            row["capability_id"] = src if row.get("status") == "unavailable" else ("%s.%s" % (src, i))
        caps.append(row)
    surface["capabilities"] = caps
    return surface


def export_capability_surface() -> dict[str, Any]:
    return validate_capability_surface(capability_surface())
