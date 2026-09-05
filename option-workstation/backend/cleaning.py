"""cleaning.py —— 十道工序清洗管道。隔离不销毁,行数对账:raw = clean + 隔离。"""
from __future__ import annotations
import math
from engine import implied_vol, fit_smile

SPREAD_PCT_MAX = {0.05: 0.35, 0.15: 0.6, 9.9: 0.9}   # |m| 分桶 → 最大价差比
CORE_TICKERS = {"SPY", "QQQ"}                          # 侯三审#3:陈旧阈值按流动性分档
STALE_S_CORE = int(__import__("os").getenv("OWS_STALE_S_CORE", "300"))    # 5min
STALE_S_OTHER = int(__import__("os").getenv("OWS_STALE_S_OTHER", "900"))  # 15min


def _spread_limit(m):
    for th, lim in sorted(SPREAD_PCT_MAX.items()):
        if abs(m) <= th:
            return lim
    return 0.9


def clean_snapshot(snap):
    """→ {clean:[...], quarantine:[...], gauges:{...}} 行=单腿(K×cp)。"""
    S, r, q = snap["spot"], snap["r"], snap["q"]
    stale_s = STALE_S_CORE if snap.get("underlying") in CORE_TICKERS else STALE_S_OTHER
    clean, quar = [], []
    total = 0
    for exp in snap["expiries"]:
        T = exp["T"]
        for row in exp["strikes"]:
            for cp in ("call", "put"):
                total += 1
                qt = row[cp]
                rec = {"dte": exp["dte"], "T": T, "K": row["K"], "cp": cp,
                       "bid": qt["bid"], "ask": qt["ask"], "oi": qt["oi"]}
                if row.get("nonstandard"):
                    quar.append({**rec, "reason": "nonstandard_contract"}); continue
                if qt["ask"] <= 0 or qt["bid"] < 0 or qt["bid"] > qt["ask"]:
                    quar.append({**rec, "reason": "crossed_or_invalid"}); continue
                if qt.get("quote_age_s", 0) > stale_s:
                    quar.append({**rec, "reason": "stale_quote"}); continue
                mid = 0.5 * (qt["bid"] + qt["ask"])
                m = math.log(row["K"] / S) if row["K"] > 0 else 0.0
                if qt["bid"] == 0.0:
                    quar.append({**rec, "reason": "zero_bid_wing"}); continue
                if mid > 0 and (qt["ask"] - qt["bid"]) / mid > _spread_limit(m):
                    quar.append({**rec, "reason": "spread_exceeds_bucket_limit"}); continue
                iv = implied_vol(mid, S, row["K"], T, r, q, cp == "call")
                if iv is None:
                    quar.append({**rec, "reason": "iv_unsolvable"}); continue
                rec.update({"mid": round(mid, 4), "iv": round(iv, 6), "m": round(m, 6)})
                clean.append(rec)
    # 套利体检:同到期 call mid 随 K 单调不增(违例→隔离,原因码)
    by_exp = {}
    for rcd in clean:
        by_exp.setdefault((rcd["dte"], rcd["cp"]), []).append(rcd)
    flagged = set()
    for (dte, cp), rows in by_exp.items():
        rows.sort(key=lambda x: x["K"])
        for a, b in zip(rows, rows[1:]):
            bad = (cp == "call" and b["mid"] > a["mid"] + 1e-6) or \
                  (cp == "put" and b["mid"] < a["mid"] - 1e-6)
            if bad:
                flagged.add(id(b))
    clean2 = []
    for rcd in clean:
        if id(rcd) in flagged:
            quar.append({**rcd, "reason": "vertical_monotonicity"})
        else:
            clean2.append(rcd)
    # 曲面拟合 + RMSE 仪表(逐到期)
    smiles = {}
    for dte in sorted({r_["dte"] for r_ in clean2}):
        pts = [(r_["m"], r_["iv"]) for r_ in clean2 if r_["dte"] == dte]
        fit = fit_smile(pts)
        if fit:
            smiles[str(dte)] = {k: round(v, 6) for k, v in fit.items()}
    worst_rmse = max((s["rmse"] for s in smiles.values()), default=None)
    gauges = {"rows_raw": total, "rows_clean": len(clean2), "rows_quarantine": len(quar),
              "reconciled": total == len(clean2) + len(quar),
              "quarantine_pct": round(100 * len(quar) / max(1, total), 2),
              "stale_pct": round(100 * sum(1 for x in quar if x["reason"] == "stale_quote") / max(1, total), 2),
              "smile_rmse_worst": (round(worst_rmse, 5) if worst_rmse is not None else None),
              "source": snap.get("source"), "ts": snap.get("ts")}
    return {"clean": clean2, "quarantine": quar, "smiles": smiles, "gauges": gauges}


def features(snap, cleaned, all_atm_iv_hist):
    """RV20 / IVR / IVP / VRP20 / Expected Move(全确定性)。"""
    hist = snap.get("hist_tail", [])
    rv20 = None
    if len(hist) >= 21:
        rets = [math.log(hist[i + 1] / hist[i]) for i in range(20)]
        mu = sum(rets) / len(rets)
        rv20 = math.sqrt(sum((x - mu) ** 2 for x in rets) / (len(rets) - 1) * 252)
    atm_iv = None
    if cleaned["clean"]:
        # O3/O6: Theta ingests actual calendar DTE (e.g. 28/32), not bucket 30.
        # Previously `dte == 30` exact match returned nothing → atm_iv30/IVP/IVR/EM null.
        # Pick the expiry whose dte is closest to 30, then the strike closest to ATM.
        nearest_dte = min(cleaned["clean"], key=lambda r: abs(r["dte"] - 30))["dte"]
        atm30 = [r_ for r_ in cleaned["clean"] if r_["dte"] == nearest_dte]
        if atm30:
            atm_iv = min(atm30, key=lambda x: abs(x["m"]))["iv"]
    ivr = ivp = None
    if atm_iv is not None and len(all_atm_iv_hist) >= 20:
        lo, hi = min(all_atm_iv_hist), max(all_atm_iv_hist)
        ivr = round(100 * (atm_iv - lo) / (hi - lo), 1) if hi > lo else None
        ivp = round(100 * sum(1 for x in all_atm_iv_hist if x <= atm_iv) / len(all_atm_iv_hist), 1)
    vrp = round((atm_iv - rv20) * 100, 2) if (atm_iv is not None and rv20 is not None) else None
    em = round(snap["spot"] * atm_iv * math.sqrt(30 / 365), 2) if atm_iv is not None else None
    return {"atm_iv30": (round(atm_iv, 4) if atm_iv else None),
            "rv20": (round(rv20, 4) if rv20 else None), "ivr": ivr, "ivp": ivp,
            "vrp20": vrp, "expected_move_30d": em}
