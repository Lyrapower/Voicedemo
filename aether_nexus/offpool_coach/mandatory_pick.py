"""Mandatory minimum coach picks — no empty window/day verdicts."""
from __future__ import annotations

import json
from typing import Any, Literal

from offpool_coach import config as cfg
from offpool_coach.schema import Payload
from offpool_coach.stage4_gate_and_log import gate_response

Window = Literal["PREMARKET", "EXECUTION"]


def mechanical_verdict_for_payload(payload: Payload, *, count: int | None = None) -> list[dict[str, Any]]:
    """Contract-compliant fallback when Fable returns [] or fails gate."""
    need = count if count is not None else cfg.MIN_COACH_PICKS_PER_WINDOW
    cands = list(payload.get("candidates") or [])
    if not cands:
        return []

    out: list[dict[str, Any]] = []
    for c in cands[: max(1, need)]:
        sym = str(c.get("ticker") or "").upper()
        if not sym:
            continue
        struct_ctx = c.get("structure_context") or {}
        liq_ctx = c.get("liquidity_context") or {}
        iv_ctx = c.get("iv_context") or {}
        # M: IV-vetoed candidates should not be mandatory-picked — the IV regime
        # was flagged as unsuitable for new positions. Previously they were still
        # emitted as grade-C picks (with iv_score=0). Skip them outright.
        if iv_ctx.get("iv_scan_veto"):
            continue
        struct_score = None if struct_ctx.get("structure_anchor_missing") else 3
        liq_cap = int(liq_ctx.get("score_cap") or cfg.LIQUIDITY_SCORE_CAP_OI_UNVERIFIED)
        liq_score = min(4, liq_cap) if liq_ctx.get("oi_unverified") else 5
        iv_score = 0 if iv_ctx.get("iv_scan_veto") else 5
        node = ["mandatory_minimum_pick"]
        if struct_ctx.get("structure_anchor_missing"):
            node.append("structure_anchor_missing")
        if liq_ctx.get("oi_unverified"):
            node.append("oi_unverified blind zone")
        out.append(
            {
                "ticker": sym,
                "grade": "C",
                "scores": {
                    "structure": struct_score,
                    "momentum": 5,
                    "liquidity": liq_score,
                    "iv_environment": iv_score,
                    "event_risk": 5,
                },
                "thesis": (
                    "Mandatory minimum pick — mechanical fallback after Fable returned empty "
                    "or failed gate. Review wounds in payload chain_summary / gate_reject."
                ),
                "falsifier": (
                    f"If {sym} spread blows out vs liquidity_context or opening structure fails, "
                    "invalidate this thesis before entry."
                ),
                "node_inferred": node,
                "execution": None,
                # H5: stamp each pick as mechanical so the emit/UI layer can distinguish
                # model-verdicted picks from rule-based fallback — not presented as if
                # the model chose them.
                "mechanical": True,
                "verdict_source": "mechanical_fallback",
            }
        )
    return out


def _pick_count(gated: dict[str, Any]) -> int:
    if not gated.get("ok"):
        return 0
    parsed = gated.get("parsed")
    return len(parsed) if isinstance(parsed, list) else 0


def ensure_minimum_verdict(raw: str, payload: Payload) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Return (raw_json_text, gated, meta). Guarantees >= MIN picks when payload has candidates."""
    meta: dict[str, Any] = {"verdict_source": "fable"}
    gated = gate_response(raw, payload)
    if _pick_count(gated) >= cfg.MIN_COACH_PICKS_PER_WINDOW:
        meta["pick_count"] = _pick_count(gated)
        return raw, gated, meta

    mech = mechanical_verdict_for_payload(payload)
    if not mech:
        meta["pick_count"] = 0
        meta["verdict_source"] = "none_no_candidates"
        return raw, gated, meta

    raw2 = json.dumps(mech, ensure_ascii=False)
    gated2 = gate_response(raw2, payload)
    meta["verdict_source"] = "mechanical_fallback"
    meta["fable_raw_excerpt"] = (raw or "")[:800]
    meta["pick_count"] = _pick_count(gated2) if gated2.get("ok") else len(mech)
    # O9: previously, if the mechanical fallback picks failed the gate, the gate was
    # overridden (mechanical_override) to force them through. Per user decision, do NOT
    # force ineligible picks through the gate — if the mechanical picks fail the gate,
    # surface the failure instead of emitting forced picks.
    if not gated2.get("ok"):
        meta["verdict_source"] = "mechanical_fallback_gate_failed"
        meta["gate_reason"] = gated2.get("reason")
        meta["gate_violations"] = gated2.get("violations")
    return raw2, gated2, meta


def pick_count_from_gated(gated: dict[str, Any]) -> int:
    return _pick_count(gated)
