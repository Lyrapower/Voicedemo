"""
PASS-first T-trade templates (Core / Satellite / Hedge).
Human-readable summaries for UI; full structure is a plain dict (JSON only for debug/snapshots).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

# --- Required output keys (verify FAIL if any missing) ---
T_TRADE_OUTPUT_KEYS: tuple[str, ...] = (
    "template_id",
    "timestamp_utc",
    "ticker",
    "decision",
    "category",
    "entry_window",
    "entry_price_range",
    "sell_price_range",
    "stop_loss",
    "size_hint",
    "rationale",
    "risk_notes",
    "required_inputs_present",
    "missing_fields",
    "cap_status",
    "cash_default_reason",
)

INACTIVE_WINDOW = "06:35–06:50 PT (not activated this evaluation; PASS-first)"
CASH_DEFAULT = "No valid T-trade opportunity under PASS-first gates."


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_regime(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower().replace("-", "_")
    if s in ("risk_on", "risk_off", "mixed", "unknown"):
        return s
    return None


def _yesno(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("yes", "no"):
        return s
    return None


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_narrative_list(v: Any) -> Optional[list[str]]:
    if v is None:
        return None
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, Iterable) and not isinstance(v, (str, bytes)):
        return [str(x).strip() for x in v if str(x).strip()]
    return None


def _missing_keys(inp: dict[str, Any], keys: list[str]) -> list[str]:
    out: list[str] = []
    for k in keys:
        if k not in inp or inp[k] is None:
            out.append(k)
            continue
        if k == "narrative_trigger" and inp[k] is not None:
            nt = _as_narrative_list(inp[k])
            if not nt:
                out.append(k)
    return out


def _pass_first_missing(inp: dict[str, Any], required: list[str]) -> tuple[bool, list[str]]:
    miss = _missing_keys(inp, required)
    return (len(miss) == 0, miss)


def _cap_status(inp: dict[str, Any]) -> str:
    w = _as_int(inp.get("weekly_trade_count"))
    if w is None:
        return "ok"
    return "capped" if w >= 3 else "ok"


def _capped(inp: dict[str, Any]) -> bool:
    return _cap_status(inp) == "capped"


def _build_decision(
    inp: dict[str, Any],
    template_id: str,
    ticker: Any,
    decision: str,
    category: Any,
    *,
    entry_window: str = INACTIVE_WINDOW,
    entry_price_range: Any = None,
    sell_price_range: Any = None,
    stop_loss: Any = None,
    size_hint: str = "tiny",
    rationale: Optional[list[str]] = None,
    risk_notes: Optional[list[str]] = None,
    required_inputs_present: str = "no",
    missing_fields: Optional[list[str]] = None,
    cash_default_reason: str = "",
) -> dict[str, Any]:
    miss = list(missing_fields or [])
    cap_st = _cap_status(inp)
    return {
        "template_id": template_id,
        "timestamp_utc": _utc_iso(),
        "ticker": ticker,
        "decision": decision,
        "category": category,
        "entry_window": entry_window,
        "entry_price_range": entry_price_range,
        "sell_price_range": sell_price_range,
        "stop_loss": stop_loss,
        "size_hint": size_hint,
        "rationale": rationale or ["No trade; PASS-first."],
        "risk_notes": risk_notes or ["Insufficient structure for a T-trade."],
        "required_inputs_present": required_inputs_present,
        "missing_fields": miss,
        "cap_status": cap_st,
        "cash_default_reason": cash_default_reason,
    }


def validate_decision_keys(d: dict[str, Any]) -> bool:
    return all(k in d for k in T_TRADE_OUTPUT_KEYS)


def decision_to_human_summary(d: dict[str, Any]) -> str:
    """Plain-language lines for UI (no JSON)."""
    lines = [
        f"Template: {d.get('template_id')}",
        f"Decision: {d.get('decision')} | Cap: {d.get('cap_status')}",
        f"Ticker: {d.get('ticker')} | Category: {d.get('category')}",
        f"Window: {d.get('entry_window')}",
    ]
    er = d.get("entry_price_range")
    sr = d.get("sell_price_range")
    sl = d.get("stop_loss")
    if er is not None:
        lines.append(f"Entry range: {er}")
    if sr is not None:
        lines.append(f"Sell range: {sr}")
    if sl is not None:
        lines.append(f"Stop: {sl}")
    lines.append(f"Size hint: {d.get('size_hint')}")
    lines.append(f"Required inputs OK: {d.get('required_inputs_present')}")
    if d.get("missing_fields"):
        lines.append("Missing: " + ", ".join(str(x) for x in d["missing_fields"]))
    lines.append("Rationale:")
    for b in d.get("rationale") or []:
        lines.append(f"  • {b}")
    lines.append("Risk:")
    for b in d.get("risk_notes") or []:
        lines.append(f"  • {b}")
    if d.get("cash_default_reason"):
        lines.append(f"Cash default: {d['cash_default_reason']}")
    return "\n".join(lines)


def _a1_gate_fail_reasons(inp: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    mr = _norm_regime(inp.get("market_regime"))
    if mr in ("unknown", "risk_off"):
        reasons.append("market_regime")
    if _yesno(inp.get("liquidity_ok")) != "yes":
        reasons.append("liquidity_ok")
    if _yesno(inp.get("spy_qqq_context")) == "fighting":
        reasons.append("spy_qqq_context")
    if inp.get("vwap_state") != "above_hold":
        reasons.append("vwap_state")
    if _yesno(inp.get("orh_break_hold")) != "yes":
        reasons.append("orh_break_hold")
    rv = _as_float(inp.get("rvol"))
    if rv is None or rv < 1.5:
        reasons.append("rvol")
    if _yesno(inp.get("sweeps_last_15m")) != "yes":
        reasons.append("sweeps_last_15m")
    return reasons


def nvda_a1_all_gates_pass(inp: dict[str, Any]) -> bool:
    if _capped(inp):
        return False
    return len(_a1_gate_fail_reasons(inp)) == 0


REQ_A1 = [
    "market_regime",
    "vwap_state",
    "orh_break_hold",
    "rvol",
    "sweeps_last_15m",
    "spy_qqq_context",
    "liquidity_ok",
    "entry_window",
    "entry_price_range",
    "sell_price_range",
    "stop_loss",
    "weekly_trade_count",
]


def eval_a1_nvda(inp: dict[str, Any]) -> dict[str, Any]:
    ok_inputs, miss = _pass_first_missing(inp, REQ_A1)
    if _capped(inp):
        return _build_decision(
            inp,
            "A1_NVDA_CORE",
            "NVDA",
            "PASS",
            "core",
            required_inputs_present="yes" if ok_inputs else "no",
            missing_fields=miss if not ok_inputs else [],
            rationale=["Weekly cap reached; hedge and core count toward cap."],
            risk_notes=["No new trades when capped."],
            cash_default_reason="Weekly trade cap (3) reached.",
        )
    if not ok_inputs:
        return _build_decision(
            inp,
            "A1_NVDA_CORE",
            None,
            "PASS",
            "core",
            required_inputs_present="no",
            missing_fields=miss,
            rationale=["Required T-trade inputs incomplete; PASS-first."],
            risk_notes=["Do not trade without full window, ranges, and stop."],
            cash_default_reason=CASH_DEFAULT,
        )
    fails = _a1_gate_fail_reasons(inp)
    if fails:
        return _build_decision(
            inp,
            "A1_NVDA_CORE",
            "NVDA",
            "PASS",
            "core",
            entry_window=str(inp.get("entry_window") or INACTIVE_WINDOW),
            entry_price_range=inp.get("entry_price_range"),
            sell_price_range=inp.get("sell_price_range"),
            stop_loss=inp.get("stop_loss"),
            required_inputs_present="yes",
            missing_fields=[],
            rationale=[f"Gate failed: {', '.join(fails)}."],
            risk_notes=["Context or structure does not meet NVDA core T-trade bar."],
            cash_default_reason=CASH_DEFAULT,
        )
    mr = _norm_regime(inp.get("market_regime"))
    size = "tiny" if mr == "mixed" else "normal" if mr == "risk_on" else "small"
    return _build_decision(
        inp,
        "A1_NVDA_CORE",
        "NVDA",
        "TRADE",
        "core",
        entry_window=str(inp["entry_window"]),
        entry_price_range=inp["entry_price_range"],
        sell_price_range=inp["sell_price_range"],
        stop_loss=inp["stop_loss"],
        size_hint=size,
        required_inputs_present="yes",
        missing_fields=[],
        rationale=[
            "VWAP above_hold + ORH break and hold.",
            "RVOL sufficient with 15m sweeps confirmation.",
            "Broad market context supportive (not fighting).",
        ],
        risk_notes=[
            "T-trade only; honor stop and sell range.",
            "Size scaled to regime (mixed → smaller).",
        ],
        cash_default_reason="",
    )


REQ_A2 = REQ_A1


def eval_a2_tsla(inp: dict[str, Any]) -> dict[str, Any]:
    if nvda_a1_all_gates_pass(inp) and _pass_first_missing(inp, REQ_A1)[0]:
        return _build_decision(
            inp,
            "A2_TSLA_CORE",
            "TSLA",
            "PASS",
            "core",
            required_inputs_present="yes",
            missing_fields=[],
            rationale=["NVDA satisfies A1 gates; TSLA is secondary — priority to NVDA."],
            risk_notes=["Satellite-style priority: do not compete with clearer NVDA setup."],
            cash_default_reason=CASH_DEFAULT,
        )
    ok_inputs, miss = _pass_first_missing(inp, REQ_A2)
    if _capped(inp):
        return _build_decision(
            inp,
            "A2_TSLA_CORE",
            "TSLA",
            "PASS",
            "core",
            required_inputs_present="yes" if ok_inputs else "no",
            missing_fields=miss if not ok_inputs else [],
            rationale=["Weekly cap reached."],
            risk_notes=["No TSLA while capped."],
            cash_default_reason="Weekly trade cap (3) reached.",
        )
    if not ok_inputs:
        return _build_decision(
            inp,
            "A2_TSLA_CORE",
            None,
            "PASS",
            "core",
            required_inputs_present="no",
            missing_fields=miss,
            cash_default_reason=CASH_DEFAULT,
        )
    mr = _norm_regime(inp.get("market_regime"))
    if mr in ("unknown", "risk_off"):
        return _build_decision(
            inp,
            "A2_TSLA_CORE",
            "TSLA",
            "PASS",
            "core",
            entry_window=str(inp.get("entry_window") or INACTIVE_WINDOW),
            required_inputs_present="yes",
            missing_fields=[],
            rationale=["Regime unknown or risk_off; TSLA requires cleaner tape."],
            cash_default_reason=CASH_DEFAULT,
        )
    if _yesno(inp.get("spy_qqq_context")) == "fighting":
        return _build_decision(inp, "A2_TSLA_CORE", "TSLA", "PASS", "core", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    if inp.get("vwap_state") != "above_hold" or _yesno(inp.get("orh_break_hold")) != "yes":
        return _build_decision(inp, "A2_TSLA_CORE", "TSLA", "PASS", "core", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    rv = _as_float(inp.get("rvol"))
    if rv is None or rv < 2.0:
        return _build_decision(inp, "A2_TSLA_CORE", "TSLA", "PASS", "core", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    if _yesno(inp.get("sweeps_last_15m")) != "yes":
        return _build_decision(inp, "A2_TSLA_CORE", "TSLA", "PASS", "core", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    size = "tiny" if mr == "mixed" else "small"
    return _build_decision(
        inp,
        "A2_TSLA_CORE",
        "TSLA",
        "TRADE",
        "core",
        entry_window=str(inp["entry_window"]),
        entry_price_range=inp["entry_price_range"],
        sell_price_range=inp["sell_price_range"],
        stop_loss=inp["stop_loss"],
        size_hint=size,
        required_inputs_present="yes",
        missing_fields=[],
        rationale=["Higher RVOL bar than NVDA; structure and sweeps confirmed."],
        risk_notes=["More volatile name; size conservative."],
        cash_default_reason="",
    )


def b0_satellite_gate_fail(inp: dict[str, Any], narrative_key: str) -> Optional[str]:
    nt = _as_narrative_list(inp.get("narrative_trigger"))
    if not nt or narrative_key not in nt:
        return "narrative_trigger"
    mr = _norm_regime(inp.get("market_regime"))
    if mr not in ("risk_on", "mixed"):
        return "market_regime"
    if _yesno(inp.get("spy_qqq_context")) == "fighting":
        return "spy_qqq_context"
    if _yesno(inp.get("liquidity_ok")) != "yes":
        return "liquidity_ok"
    w = _as_int(inp.get("weekly_trade_count"))
    if w is None or w >= 3:
        return "weekly_trade_count"
    return None


REQ_B1 = [
    "market_regime",
    "narrative_trigger",
    "vwap_state",
    "rvol",
    "liquidity_ok",
    "spy_qqq_context",
    "entry_window",
    "entry_price_range",
    "sell_price_range",
    "stop_loss",
    "weekly_trade_count",
]


def eval_b1_pltr(inp: dict[str, Any]) -> dict[str, Any]:
    key = "defense_ai"
    b0 = b0_satellite_gate_fail(inp, key)
    ok_inputs, miss = _pass_first_missing(inp, REQ_B1)
    if b0 or not ok_inputs:
        m = (miss if not ok_inputs else []) + ([b0] if b0 else [])
        return _build_decision(
            inp,
            "B1_PLTR_DEFENSE_AI",
            "PLTR",
            "PASS",
            "satellite",
            required_inputs_present="yes" if ok_inputs else "no",
            missing_fields=m,
            cash_default_reason=CASH_DEFAULT,
        )
    if inp.get("vwap_state") != "above_hold":
        return _build_decision(inp, "B1_PLTR_DEFENSE_AI", "PLTR", "PASS", "satellite", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    rv = _as_float(inp.get("rvol"))
    if rv is None or rv < 1.3:
        return _build_decision(inp, "B1_PLTR_DEFENSE_AI", "PLTR", "PASS", "satellite", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    return _build_decision(
        inp,
        "B1_PLTR_DEFENSE_AI",
        "PLTR",
        "TRADE",
        "satellite",
        entry_window=str(inp["entry_window"]),
        entry_price_range=inp["entry_price_range"],
        sell_price_range=inp["sell_price_range"],
        stop_loss=inp["stop_loss"],
        size_hint="small",
        required_inputs_present="yes",
        missing_fields=[],
        rationale=[f"narrative_trigger includes {key}; bottleneck thesis active.", "Structure: VWAP above_hold with confirming RVOL."],
        risk_notes=["Satellite only when narrative explicit; not a fallback."],
        cash_default_reason="",
    )


REQ_B2 = REQ_B1 + ["crypto_flow_supportive"]


def eval_b2_coin(inp: dict[str, Any]) -> dict[str, Any]:
    key = "crypto_flows"
    b0 = b0_satellite_gate_fail(inp, key)
    ok_inputs, miss = _pass_first_missing(inp, REQ_B2)
    if b0 or not ok_inputs:
        m = (miss if not ok_inputs else []) + ([b0] if b0 else [])
        return _build_decision(
            inp,
            "B2_COIN_CRYPTO_FLOWS",
            "COIN",
            "PASS",
            "satellite",
            required_inputs_present="yes" if ok_inputs else "no",
            missing_fields=m,
            cash_default_reason=CASH_DEFAULT,
        )
    if _yesno(inp.get("crypto_flow_supportive")) != "yes":
        return _build_decision(inp, "B2_COIN_CRYPTO_FLOWS", "COIN", "PASS", "satellite", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    rv = _as_float(inp.get("rvol"))
    if rv is None or rv < 1.5:
        return _build_decision(inp, "B2_COIN_CRYPTO_FLOWS", "COIN", "PASS", "satellite", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    return _build_decision(
        inp,
        "B2_COIN_CRYPTO_FLOWS",
        "COIN",
        "TRADE",
        "satellite",
        entry_window=str(inp["entry_window"]),
        entry_price_range=inp["entry_price_range"],
        sell_price_range=inp["sell_price_range"],
        stop_loss=inp["stop_loss"],
        size_hint="small",
        required_inputs_present="yes",
        missing_fields=[],
        rationale=["crypto_flows narrative active; flows supportive flag on.", "RVOL confirms participation."],
        risk_notes=["Proxy name; size controlled."],
        cash_default_reason="",
    )


REQ_B3 = REQ_B1


def eval_b3_corz(inp: dict[str, Any]) -> dict[str, Any]:
    key = "mining_to_ai"
    b0 = b0_satellite_gate_fail(inp, key)
    ok_inputs, miss = _pass_first_missing(inp, REQ_B3)
    if b0 or not ok_inputs:
        m = (miss if not ok_inputs else []) + ([b0] if b0 else [])
        return _build_decision(
            inp,
            "B3_CORZ_MINING_TO_AI",
            "CORZ",
            "PASS",
            "satellite",
            required_inputs_present="yes" if ok_inputs else "no",
            missing_fields=m,
            cash_default_reason=CASH_DEFAULT,
        )
    if inp.get("vwap_state") != "above_hold":
        return _build_decision(inp, "B3_CORZ_MINING_TO_AI", "CORZ", "PASS", "satellite", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    rv = _as_float(inp.get("rvol"))
    if rv is None or rv < 1.5:
        return _build_decision(inp, "B3_CORZ_MINING_TO_AI", "CORZ", "PASS", "satellite", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    return _build_decision(
        inp,
        "B3_CORZ_MINING_TO_AI",
        "CORZ",
        "TRADE",
        "satellite",
        entry_window=str(inp["entry_window"]),
        entry_price_range=inp["entry_price_range"],
        sell_price_range=inp["sell_price_range"],
        stop_loss=inp["stop_loss"],
        size_hint="tiny",
        required_inputs_present="yes",
        missing_fields=[],
        rationale=["mining_to_ai narrative explicit; transition theme only.", "Low liquidity: size forced tiny."],
        risk_notes=["Illiquid satellite; PASS most days without narrative."],
        cash_default_reason="",
    )


REQ_B4 = REQ_B1


def eval_b4_be(inp: dict[str, Any]) -> dict[str, Any]:
    key = "power_constraint"
    b0 = b0_satellite_gate_fail(inp, key)
    ok_inputs, miss = _pass_first_missing(inp, REQ_B4)
    if b0 or not ok_inputs:
        m = (miss if not ok_inputs else []) + ([b0] if b0 else [])
        return _build_decision(
            inp,
            "B4_BE_POWER_BOTTLENECK",
            "BE",
            "PASS",
            "satellite",
            required_inputs_present="yes" if ok_inputs else "no",
            missing_fields=m,
            cash_default_reason=CASH_DEFAULT,
        )
    if inp.get("vwap_state") != "above_hold":
        return _build_decision(inp, "B4_BE_POWER_BOTTLENECK", "BE", "PASS", "satellite", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    rv = _as_float(inp.get("rvol"))
    if rv is None or rv < 1.3:
        return _build_decision(inp, "B4_BE_POWER_BOTTLENECK", "BE", "PASS", "satellite", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    mr = _norm_regime(inp.get("market_regime"))
    size = "tiny" if mr == "mixed" else "small"
    return _build_decision(
        inp,
        "B4_BE_POWER_BOTTLENECK",
        "BE",
        "TRADE",
        "satellite",
        entry_window=str(inp["entry_window"]),
        entry_price_range=inp["entry_price_range"],
        sell_price_range=inp["sell_price_range"],
        stop_loss=inp["stop_loss"],
        size_hint=size,
        required_inputs_present="yes",
        missing_fields=[],
        rationale=[
            "power_constraint narrative: upstream power/bandwidth bottleneck priced vs downstream compute heat.",
            "Relative strength vs pure downstream beta.",
        ],
        risk_notes=["Narrative must name power_constraint; otherwise cash.", "No story trading beyond stated structure."],
        cash_default_reason="",
    )


REQ_C1 = [
    "market_regime",
    "spy_qqq_context",
    "entry_window",
    "entry_price_range",
    "sell_price_range",
    "stop_loss",
    "weekly_trade_count",
]


def eval_c1_sqqq(inp: dict[str, Any]) -> dict[str, Any]:
    ok_inputs, miss = _pass_first_missing(inp, REQ_C1)
    if _capped(inp):
        return _build_decision(
            inp,
            "C1_SQQQ_HEDGE",
            "SQQQ",
            "PASS",
            "hedge",
            required_inputs_present="yes" if ok_inputs else "no",
            missing_fields=miss if not ok_inputs else [],
            cash_default_reason="Weekly trade cap (3) reached.",
        )
    if not ok_inputs:
        return _build_decision(
            inp,
            "C1_SQQQ_HEDGE",
            None,
            "PASS",
            "hedge",
            required_inputs_present="no",
            missing_fields=miss,
            cash_default_reason=CASH_DEFAULT,
        )
    mr = _norm_regime(inp.get("market_regime"))
    if mr != "risk_off":
        return _build_decision(inp, "C1_SQQQ_HEDGE", "SQQQ", "PASS", "hedge", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    if _yesno(inp.get("spy_qqq_context")) != "fighting":
        return _build_decision(inp, "C1_SQQQ_HEDGE", "SQQQ", "PASS", "hedge", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    return _build_decision(
        inp,
        "C1_SQQQ_HEDGE",
        "SQQQ",
        "TRADE",
        "hedge",
        entry_window=str(inp["entry_window"]),
        entry_price_range=inp["entry_price_range"],
        sell_price_range=inp["sell_price_range"],
        stop_loss=inp["stop_loss"],
        size_hint="small",
        required_inputs_present="yes",
        missing_fields=[],
        rationale=["risk_off regime with indices fighting; tech downside hedge slot."],
        risk_notes=["Hedge counts toward weekly cap."],
        cash_default_reason="",
    )


REQ_C2 = REQ_C1 + ["macro_shock"]


def eval_c2_gld(inp: dict[str, Any]) -> dict[str, Any]:
    ok_inputs, miss = _pass_first_missing(inp, REQ_C2)
    if _capped(inp):
        return _build_decision(
            inp,
            "C2_GLD_HEDGE",
            "GLD",
            "PASS",
            "hedge",
            required_inputs_present="yes" if ok_inputs else "no",
            missing_fields=miss if not ok_inputs else [],
            cash_default_reason="Weekly trade cap (3) reached.",
        )
    if not ok_inputs:
        return _build_decision(
            inp,
            "C2_GLD_HEDGE",
            None,
            "PASS",
            "hedge",
            required_inputs_present="no",
            missing_fields=miss,
            cash_default_reason=CASH_DEFAULT,
        )
    if _yesno(inp.get("macro_shock")) != "yes":
        return _build_decision(inp, "C2_GLD_HEDGE", "GLD", "PASS", "hedge", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    mr = _norm_regime(inp.get("market_regime"))
    if mr != "risk_off":
        return _build_decision(inp, "C2_GLD_HEDGE", "GLD", "PASS", "hedge", required_inputs_present="yes", missing_fields=[], cash_default_reason=CASH_DEFAULT)
    return _build_decision(
        inp,
        "C2_GLD_HEDGE",
        "GLD",
        "TRADE",
        "hedge",
        entry_window=str(inp["entry_window"]),
        entry_price_range=inp["entry_price_range"],
        sell_price_range=inp["sell_price_range"],
        stop_loss=inp["stop_loss"],
        size_hint="small",
        required_inputs_present="yes",
        missing_fields=[],
        rationale=["macro_shock confirmed; risk_off; GLD hedge slot."],
        risk_notes=["Hedge counts toward cap; event-driven only."],
        cash_default_reason="",
    )


def evaluate_t_trade(inp: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    Priority: A1 NVDA → A2 TSLA → B1–B4 → C1 → C2.
    First TRADE wins; else aggregate PASS_DEFAULT.
    """
    inp = dict(inp or {})
    evaluators = [
        eval_a1_nvda,
        eval_a2_tsla,
        eval_b1_pltr,
        eval_b2_coin,
        eval_b3_corz,
        eval_b4_be,
        eval_c1_sqqq,
        eval_c2_gld,
    ]
    for fn in evaluators:
        d = fn(inp)
        if not validate_decision_keys(d):
            raise RuntimeError(f"template bug: missing keys from {fn.__name__}")
        if d.get("decision") == "TRADE":
            return d
    rip = "yes" if inp.get("market_regime") is not None else "no"
    return _build_decision(
        inp,
        "PASS_DEFAULT",
        None,
        "PASS",
        None,
        required_inputs_present=rip,
        missing_fields=[],
        rationale=["No template produced TRADE under PASS-first gates."],
        risk_notes=["Default cash until a full T-trade setup appears."],
        cash_default_reason=CASH_DEFAULT,
    )


def inputs_from_workspace_state(state: dict[str, Any]) -> dict[str, Any]:
    """Map local workspace snapshot into template inputs (mostly unknown → PASS)."""
    reg = str(state.get("current_regime") or "unknown").strip()
    mr = _norm_regime(reg) or "unknown"
    nar = str(state.get("current_active_narrative") or "none").strip()
    triggers: Optional[list[str]] = None if nar in ("", "none") else [nar]
    return {
        "market_regime": mr,
        "narrative_trigger": triggers,
        "weekly_trade_count": int(state.get("weekly_trade_count") or 0),
        "liquidity_ok": None,
        "vwap_state": None,
        "orh_break_hold": None,
        "rvol": None,
        "sweeps_last_15m": None,
        "spy_qqq_context": None,
        "entry_window": None,
        "entry_price_range": None,
        "sell_price_range": None,
        "stop_loss": None,
        "crypto_flow_supportive": None,
        "macro_shock": None,
    }
