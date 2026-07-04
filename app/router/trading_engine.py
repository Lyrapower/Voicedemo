"""
Trading evaluation entrypoint: permission gate, weekly cap, missing fields, then templates.
"""
from __future__ import annotations

from typing import Any, Optional

from app.router.trade_templates import (
    REQ_A1,
    decision_to_human_summary,
    evaluate_t_trade,
    inputs_from_workspace_state,
)

GATE_REASONS = frozenset({"NO_ACTIVE_CONSTRAINT", "WEEKLY_CAP_REACHED", "MISSING_FIELDS"})


def _weekly_count(state: dict[str, Any]) -> int:
    raw = state.get("weekly_trade_count", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _missing_required_template_fields(state: dict[str, Any], required: list[str]) -> list[str]:
    miss: list[str] = []
    for k in required:
        if k not in state or state.get(k) is None:
            miss.append(k)
            continue
        if k == "narrative_trigger":
            v = state.get(k)
            if v is not None and isinstance(v, list) and len(v) == 0:
                miss.append(k)
    return miss


def _merged_trade_inputs(state: dict[str, Any]) -> dict[str, Any]:
    base = inputs_from_workspace_state(state)
    for k in base:
        if k in state:
            base[k] = state[k]
    return base


def evaluate_trading_decision(state: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    Prod entrypoint: hard gates on workspace state, then evaluate_t_trade(template inputs).
    Early exits return compact dicts; success returns full template output unchanged.
    """
    state = dict(state or {})

    active_required = bool(state.get("trading_permission_active_required", True))
    permission_granted = bool(state.get("permission_granted", state.get("active_constraints_present", False)))

    if active_required and not permission_granted:
        return {
            "decision": "PASS",
            "reason": "NO_ACTIVE_CONSTRAINT",
            "cash_default": True,
            "weekly_cap_ok": True,
            "fields_missing": [],
        }

    if _weekly_count(state) >= 3:
        return {
            "decision": "PASS",
            "reason": "WEEKLY_CAP_REACHED",
            "cash_default": True,
            "weekly_cap_ok": False,
            "fields_missing": [],
        }

    missing = _missing_required_template_fields(state, list(REQ_A1))
    if missing:
        return {
            "decision": "PASS",
            "reason": "MISSING_FIELDS",
            "cash_default": True,
            "weekly_cap_ok": True,
            "fields_missing": missing,
        }

    inp = _merged_trade_inputs(state)
    return evaluate_t_trade(inp)


def trading_decision_human_lines(d: dict[str, Any]) -> list[str]:
    """Human lines for UI: gate exits stay plain text; template output uses existing formatter."""
    r = d.get("reason")
    if r in GATE_REASONS:
        lines = [
            f"Decision: {d.get('decision')}",
            f"Reason: {r}",
            f"Cash default: {d.get('cash_default')}",
            f"Weekly cap OK: {d.get('weekly_cap_ok')}",
        ]
        fm = d.get("fields_missing") or []
        if fm:
            lines.append("Missing fields: " + ", ".join(str(x) for x in fm))
        return lines
    return decision_to_human_summary(d).splitlines()
