"""strategy.py —— 策略引擎:任意腿、盈亏平衡、最大亏损、POP、情景矩阵、成交现实性。
入场价 = mid ± FILL_K×半价差(买加卖减);spread_cost_pct 印在卡上。全确定性。
"""
from __future__ import annotations
import math, os
from engine import bs_price, pop_lognormal

FILL_K = float(os.getenv("OWS_FILL_K", "0.5"))     # 0=mid 成交,1=全价差


def _leg_quote(cleaned, dte, K, cp):
    for r_ in cleaned["clean"]:
        if r_["dte"] == dte and abs(r_["K"] - K) < 1e-9 and r_["cp"] == cp:
            return r_
    return None


def evaluate(snap, cleaned, legs, atm_iv):
    """legs: [{dte,K,cp,side(+1买/-1卖),qty}] → 策略卡。"""
    S, r, q = snap["spot"], snap["r"], snap["q"]
    entry = 0.0; spread_cost = 0.0; detail = []
    for lg in legs:
        qt = _leg_quote(cleaned, lg["dte"], lg["K"], lg["cp"])
        if qt is None:
            return {"error": "腿不可成交:该合约不在清洗后数据中(K=%s %s %sd)——"
                             "七问第6问红" % (lg["K"], lg["cp"], lg["dte"])}
        half = (qt["ask"] - qt["bid"]) / 2 if qt["ask"] > qt["bid"] else 0.0
        px = qt["mid"] + lg["side"] * FILL_K * half
        entry += lg["side"] * px * lg["qty"]
        spread_cost += FILL_K * half * lg["qty"]
        detail.append({**lg, "mid": qt["mid"], "fill": round(px, 4), "iv": qt["iv"],
                       "spread_pct": round(100 * 2 * half / max(qt["mid"], 1e-9), 1)})

    def payoff_at_expiry(sT):
        v = -entry
        for lg in legs:
            intr = max(0.0, (sT - lg["K"]) if lg["cp"] == "call" else (lg["K"] - sT))
            v += lg["side"] * intr * lg["qty"]
        return v

    # 盈亏平衡 + 最大亏损(宽网格扫描;裸卖翼→无界标记)
    grid = [S * (0.5 + i * 1.5 / 480) for i in range(481)]
    pays = [payoff_at_expiry(x) for x in grid]
    bes = []
    for a, b, pa, pb in zip(grid, grid[1:], pays, pays[1:]):
        if pa == 0 or (pa < 0 < pb) or (pb < 0 < pa):
            bes.append(round(a + (b - a) * (0 - pa) / (pb - pa + 1e-12), 2))
    net_call = sum(lg["side"] * lg["qty"] for lg in legs if lg["cp"] == "call")
    net_put = sum(lg["side"] * lg["qty"] for lg in legs if lg["cp"] == "put")
    unbounded = net_call < 0 or net_put < 0
    max_loss = None if unbounded else round(min(pays) * 100, 2)
    max_profit = round(max(pays) * 100, 2)
    T = min(lg["dte"] for lg in legs) / 365.0
    pop = pop_lognormal(S, T, atm_iv or 0.2, payoff_at_expiry)
    prem_base = abs(entry) if abs(entry) > 1e-9 else abs(max_profit) / 100 or 1e-9
    card = {"entry_debit": round(entry, 4), "legs": detail,
            "breakevens": bes, "max_loss": max_loss,
            "max_loss_note": ("无界(含裸卖翼)" if unbounded else None),
            "max_profit": max_profit, "pop": round(pop * 100, 1),
            "spread_cost": round(spread_cost * 100, 2),
            "spread_cost_pct_of_premium": round(100 * spread_cost / prem_base, 1),
            "pop_note": "对数正态·ATM IV·零漂移(研究口径)"}
    # 情景矩阵:价格×IV 平移×剩余时间(BS 重定价,美式近似为欧式已标注)
    iv_shifts = [-0.05, 0.0, 0.05]
    t_lefts = sorted({0, round(T * 0.5, 4), round(T, 4)})
    prices = [round(S * (1 + s), 2) for s in (-0.05, -0.02, 0, 0.02, 0.05)]
    matrix = []
    for tl in t_lefts:
        for dv in iv_shifts:
            rowv = []
            for px in prices:
                v = -entry
                for lg, d in zip(legs, detail):
                    tt = max(0.0, lg["dte"] / 365.0 - (T - tl))
                    vv = max(0.02, d["iv"] + dv)
                    v += lg["side"] * bs_price(px, lg["K"], tt, r, q, vv, lg["cp"] == "call") * lg["qty"]
                rowv.append(round(v * 100, 1))
            matrix.append({"t_left_d": round(tl * 365), "iv_shift": dv, "prices": prices, "pnl": rowv})
    card["scenario"] = matrix
    card["scenario_note"] = "BS 重定价(美式近似欧式,已标注)"
    return card
