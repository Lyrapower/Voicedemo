"""Structured gateway responses — separate computed verdict from draft echo."""
from __future__ import annotations

import time

# P0 link fingerprint — absence on response ⇒ traffic did not traverse :8501 gateway
SERVED_BY = "gateway-v4.11"
GATEWAY_STARTED_AT: float | None = None


def set_gateway_started_at(ts: float) -> None:
    global GATEWAY_STARTED_AT
    GATEWAY_STARTED_AT = ts


def link_fingerprint(route_id: str) -> dict:
    out = {
        "served_by": SERVED_BY,
        "route_id": route_id,
        "ts": time.time(),
    }
    if GATEWAY_STARTED_AT is not None:
        out["gateway_started_at"] = GATEWAY_STARTED_AT
    return out


CONTRACT_PREFIXES = ("CONTRACT:", "PREFILTER", "DEEP_ROUTE", "SUBSTRATE_NULL", "BLOCKED", "VERIFIED")


def is_deterministic_output(*, routed_to: str, blocked: bool, contract_suffix: str | None) -> bool:
    if contract_suffix:
        return True
    if blocked:
        return True
    rt = routed_to or ""
    if any(p in rt for p in ("CONTRACT:", "BLOCKED", "SUBSTRATE_NULL", "pre_filter", "deep")):
        return True
    return False


def computed_verdict_from_route(
    *,
    routed_to: str,
    blocked: bool,
    contract_suffix: str | None = None,
) -> str:
    if contract_suffix:
        return contract_suffix
    rt = routed_to or ""
    if rt.startswith("local:"):
        suffix = rt[len("local:"):]
        if suffix:
            return suffix
    if rt.startswith("unsafe_debug:"):
        return rt[len("unsafe_debug:"):]
    if rt == "pre_filter":
        return "PREFILTER"
    if rt == "deep":
        return "DEEP_ROUTE"
    if blocked or "BLOCKED" in rt:
        return "BLOCKED"
    if "SUBSTRATE_NULL" in rt:
        return "SUBSTRATE_NULL"
    return "DRAFT_ECHO"


def build_gateway_envelope(
    *,
    route_id: str,
    routed_to: str,
    response: str,
    coherence_score: float,
    blocked: bool = False,
    reason: str | None = None,
    contract_suffix: str | None = None,
    **extra,
) -> dict:
    computed = computed_verdict_from_route(
        routed_to=routed_to, blocked=blocked, contract_suffix=contract_suffix,
    )
    deterministic = is_deterministic_output(
        routed_to=routed_to, blocked=blocked, contract_suffix=contract_suffix,
    )
    return {
        **link_fingerprint(route_id),
        "route_id": route_id,
        "routed_to": routed_to,
        "coherence_score": coherence_score,
        "response": response,
        "computed_verdict": computed,
        "draft_only": not deterministic,
        "blocked": blocked,
        "reason": reason,
        **extra,
    }
