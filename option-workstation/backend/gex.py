"""gex.py —— Net GEX / Gamma Flip。假设上屏:符号约定=做市商净空客户流
(call OI 记正、put OI 记负);OI 归因未知——这是模型,不是数据。"""
from __future__ import annotations
from engine import greeks

ASSUMPTION = "假设:dealer 净多 call / 净空 put(朴素约定);OI 未归因。模型≠数据。"


def net_gex(snap, cleaned):
    S, r, q = snap["spot"], snap["r"], snap["q"]
    per_strike = {}
    total_oi = 0
    for rec in cleaned["clean"]:
        total_oi += int(rec.get("oi") or 0)
        g = greeks(S, rec["K"], rec["T"], r, q, rec["iv"], rec["cp"] == "call")["gamma"]
        contrib = g * rec["oi"] * 100 * S * S * 0.01 / 1e6      # $M / 1% move
        sign = 1.0 if rec["cp"] == "call" else -1.0
        per_strike[rec["K"]] = per_strike.get(rec["K"], 0.0) + sign * contrib
    ks = sorted(per_strike)
    total = sum(per_strike.values())
    flip = None
    cum = 0.0
    for a, b in zip(ks, ks[1:]):
        c0, c1 = cum + per_strike[a], cum + per_strike[a] + per_strike[b]
        cum += per_strike[a]
        if (c0 <= 0 <= c1) or (c1 <= 0 <= c0):
            flip = round(a + (b - a) * (0 - c0) / (c1 - c0 + 1e-12), 2)
            break
    # M: with OI=0 (Theta FREE tier) GEX sums to ~0 and gamma_flip is meaningless.
    # Flag it explicitly so the UI/LLM doesn't present a near-zero GEX as a real signal.
    oi_missing = total_oi == 0
    return {"net_gex_musd_per_1pct": round(total, 1),
            "by_strike": [{"K": k, "gex": round(v, 2)} for k, v in sorted(per_strike.items())],
            "gamma_flip": flip, "assumption": ASSUMPTION,
            "oi_missing": oi_missing,
            "gex_unreliable": oi_missing}
