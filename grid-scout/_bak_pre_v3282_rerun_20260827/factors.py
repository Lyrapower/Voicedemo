"""factors.py · Scout v3.29 因子核(2026-08-25,Lyra 令"当然继续",把 Fable 一个月前 A/C 组讨论落成代码)

替代 v3.26–v3.28 里近 30 条手写加分规则(候选池 12 条 + 趋势榜 8 条 + 财报名单 7 条)——那些规则每条对应某一天的事故,
是对最近三张截图的过拟合。这里只有 6 个因子,每个有经济含义、有显式权重、有 why 字符串;因子预算上限 12(verify 静态闸)。

    F1 money   资金密度  权 20  换手率 = 20 日成交额 / 市值(成交额/流通市值的可得近似);缺市值退成交额档
    F2 trend   趋势      权 25  5 日涨幅 / 10 日涨幅 / 近 5 根收涨根数 / 距 20 日高
    F3 tape    尾盘形态  权 15  收盘在日内区间的位置 / 当日涨跌 / 放量倍数
    F4 event   事件      权 15  距财报天数(3–7 天 = IV 抬升窗,long call 吃 IV expansion;当日 AMC = 只准预排)
    F5 options 不对称性  权 20  ATM 最近到期(7–30 DTE)call 的 gamma/|theta|,批内百分位;Theta 快照缺 = 因子缺,权重归一化到可得因子
    F6 risk    风险扣分         RSI>85 −15 / 5 日 >40% −15(追高)/ 当日 >20% −10 / 双杀位 −10 / 弱势收低(≤−1% 且 loc<0.5)−20

总分 = Σ(权_i × 子分_i)/Σ(可得因子权)− 扣分,0–100 整数。地板(price/adv20/ETF)与方向闸是准入,不是因子,不在此文件。

宏观(C#4)只进仓位档不进选股:regime_tier() 按 VIX 定 满/半/停,只显示。
Kelly(C#8):kelly_fraction() 由复盘账本滚动命中率算,样本 <20 用 quarter,≥20 用 half;只显示。
"""
from __future__ import annotations

import math
import os

WEIGHTS = {"F1_money": 20, "F2_trend": 25, "F3_tape": 15, "F4_event": 15, "F5_options": 20}      # swing 视角(趋势榜/财报名单/预排)
# v3.29.3:T+0 视角(晨/午班 0DTE 卡)——当日形态与期权不对称性权重上调,多日趋势下调;同六因子,只换权重
WEIGHTS_T0 = {"F1_money": 20, "F2_trend": 15, "F3_tape": 30, "F4_event": 10, "F5_options": 25}
VIEWS = {"swing": WEIGHTS, "t0": WEIGHTS_T0}
FACTOR_BUDGET = 12          # 因子数硬上限(Fable 8 月讨论:>12 进过拟合危险区)
FACTORS = ("F1_money", "F2_trend", "F3_tape", "F4_event", "F5_options", "F6_risk")
assert len(FACTORS) <= FACTOR_BUDGET


def _clip(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _lerp(x, x0, y0, x1, y1):
    """x 在 [x0,x1] 线性映射到 [y0,y1],外侧截断。"""
    if x is None:
        return None
    if x <= x0:
        return y0
    if x >= x1:
        return y1
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


# ---------------- F1 资金密度 ----------------
def f1_money(d):
    """换手率(20 日成交额/市值)为主;缺市值时退到 20 日成交额绝对档。返回 (子分, why)。"""
    adv = d.get("adv20_usd")
    mcap_b = d.get("mcap_b")
    if adv is None:
        return None, "F1 无成交额"
    if mcap_b and mcap_b > 0:
        turnover = adv / (mcap_b * 1e9)          # 日均换手(20 日)
        # 0.1% → 0,0.3% → 30,1% → 60,3% → 100(对数轴上大致线性)
        sub = _clip(_lerp(math.log10(max(turnover, 1e-5)), math.log10(0.001), 0, math.log10(0.03), 100))
        return sub, "换手%.2f%%/日" % (turnover * 100)
    sub = _clip(_lerp(math.log10(max(adv, 1)), math.log10(1e8), 40, math.log10(2e9), 100))
    return sub, "成交额$%.0fM(无市值)" % (adv / 1e6)


# ---------------- F2 趋势 ----------------
def f2_trend(d):
    c5, c10, up5, h20 = d.get("chg5_pct"), d.get("chg10_pct"), d.get("up5"), d.get("dist_high20_pct")
    if c5 is None:
        return None, "F2 无 5 日读数"
    parts, why = [], []
    # 5 日:−5% → 0,0 → 20,+5% → 60,+15% → 100;>40% 封顶 100 但 F6 扣追高
    parts.append(_clip(_lerp(c5, -5, 0, 15, 100)) if c5 <= 15 else 100); why.append("5日%+.1f%%" % c5)
    if c10 is not None:
        parts.append(_clip(_lerp(c10, -5, 0, 25, 100))); why.append("10日%+.1f%%" % c10)
    if up5 is not None:
        parts.append(_clip(up5 / 5 * 100)); why.append("5根%d涨" % up5)
    if h20 is not None:
        parts.append(_clip(_lerp(h20, -10, 0, 0, 100))); why.append("距20日高%+.1f%%" % h20)
    return sum(parts) / len(parts), " ".join(why)


# ---------------- F3 尾盘形态 ----------------
def f3_tape(d):
    loc, chg, vx = d.get("close_loc"), d.get("chg_pct"), d.get("vol_x20")
    if loc is None and chg is None:
        return None, "F3 无形态读数"
    parts, why = [], []
    if loc is not None:
        parts.append(_clip(loc * 100)); why.append("loc%.2f" % loc)
    if chg is not None:
        parts.append(_clip(_lerp(chg, -3, 0, 5, 100))); why.append("日%+.1f%%" % chg)
    if vx is not None:
        parts.append(_clip(_lerp(vx, 0.7, 20, 2.0, 100))); why.append("量%.1fx" % vx)
    return sum(parts) / len(parts), " ".join(why)


# ---------------- F4 事件 ----------------
def f4_event(days_to_earnings, post_days=None, post_gap_pct=None):
    """days_to_earnings:距下一财报的交易日数(0=今日盘后,1=明日盘前…);None=窗内无财报。
    3–7 天 = IV 抬升窗 100;1–2 天 70(IV 已大半抬升);8–14 天 40;0 天 = 不计分(只准预排,由闸管);
    post_days 1–3 且 post_gap_pct ≥ +5% = 财报后漂移 60。"""
    if days_to_earnings is not None:
        n = int(days_to_earnings)
        if n == 0:
            return 0.0, "财报今日盘后(预排)"
        if 3 <= n <= 7:
            return 100.0, "财报%d天(IV窗)" % n
        if 1 <= n <= 2:
            return 70.0, "财报%d天" % n
        if 8 <= n <= 14:
            return 40.0, "财报%d天" % n
    if post_days is not None and 1 <= int(post_days) <= 3 and (post_gap_pct or 0) >= 5:
        return 60.0, "财报后%d天 gap%+.1f%%" % (post_days, post_gap_pct)
    return None, "无事件"


# ---------------- F5 期权不对称性 ----------------
def f5_options_ratio(g):
    """g = {gamma, theta, iv, dte, strike, mid}(Theta ATM call 快照);返回 gamma/|theta| 原始比值或 None。"""
    if not g or g.get("gamma") is None or not g.get("theta"):
        return None
    th = abs(float(g["theta"]))
    if th < 1e-6:
        return None
    return float(g["gamma"]) / th


def f5_options_batch(ratios):
    """批内百分位:{sym: ratio} → {sym: 子分};单票 50;None 不计。"""
    vals = sorted(v for v in ratios.values() if v is not None)
    out = {}
    for s, v in ratios.items():
        if v is None:
            out[s] = None
        elif len(vals) <= 1:
            out[s] = 50.0
        else:
            rank = sum(1 for x in vals if x < v)
            out[s] = rank / (len(vals) - 1) * 100
    return out


# ---------------- F6 风险扣分 ----------------
def f6_risk(d):
    pen, why = 0, []
    rsi, c5, chg = d.get("rsi14"), d.get("chg5_pct"), d.get("chg_pct")
    if rsi is not None and rsi > 85:
        pen += 15; why.append("RSI%.0f过热-15" % rsi)
    if c5 is not None and c5 > 40:
        pen += 15; why.append("5日%+.0f%%追高-15" % c5)
    if chg is not None and chg > 20:
        pen += 10; why.append("日%+.0f%%单日暴涨-10" % chg)
    if d.get("dk_risk"):
        pen += 10; why.append("双杀位-10")
    loc = d.get("close_loc")
    if chg is not None and loc is not None and chg <= -1.0 and loc < 0.5:
        pen += 20; why.append("弱势收低-20")      # 与方向闸同判据(闸=硬作废,此处=软扣分,池内排位也要反映)
    return pen, " ".join(why)


# ---------------- 汇总 ----------------
def score(d, *, days_to_earnings=None, post_days=None, post_gap_pct=None, f5_sub=None, f5_raw=None, view="swing"):
    """→ {"score": int 0–100, "subs": {F: 子分或 None}, "why": str, "missing": [F...], "penalty": int, "view": str}
    view = "swing"(多日,默认)/ "t0"(晨午班 0DTE:F3/F5 权重上调)。"""
    W = VIEWS.get(view, WEIGHTS)
    subs, whys = {}, {}
    subs["F1_money"], whys["F1_money"] = f1_money(d)
    subs["F2_trend"], whys["F2_trend"] = f2_trend(d)
    subs["F3_tape"], whys["F3_tape"] = f3_tape(d)
    subs["F4_event"], whys["F4_event"] = f4_event(days_to_earnings, post_days, post_gap_pct)
    subs["F5_options"] = f5_sub
    whys["F5_options"] = ("γ/|θ|=%.2f" % f5_raw) if (f5_raw is not None) else "F5 缺(Theta 无快照)"
    pen, pen_why = f6_risk(d)
    # F4 "无事件"按 None 处理(不参与归一化),只有有窗口时才有权重——否则无财报票天然吃亏
    avail = {k: v for k, v in subs.items() if v is not None}
    wsum = sum(W[k] for k in avail)
    total = (sum(W[k] * v for k, v in avail.items()) / wsum) if wsum else 0.0
    total = _clip(total - pen)
    missing = [k for k, v in subs.items() if v is None]
    why = " | ".join("%s %s%s" % (k[:2], ("%.0f" % v) if v is not None else "-", ("(" + whys[k] + ")") if whys[k] else "")
                     for k, v in subs.items())
    if pen_why:
        why += " | F6 " + pen_why
    return {"score": int(round(total)), "subs": {k: (None if v is None else round(v, 1)) for k, v in subs.items()},
            "why": why, "missing": missing, "penalty": pen, "view": view}


# ---------------- 宏观仓位档(只显示,不进选股) ----------------
def regime_tier(vix_level, vix_chg_pct=None):
    """VIX <18 满;18–25 半;>25 停(只观察);VIX 单日 ≥ +15% 降一档。返回 (档, 理由)。"""
    if vix_level is None:
        return "未知", "VIX 无读数"
    tiers = ["满", "半", "停"]
    i = 0 if vix_level < 18 else (1 if vix_level <= 25 else 2)
    why = "VIX %.1f" % vix_level
    if vix_chg_pct is not None and vix_chg_pct >= 15 and i < 2:
        i += 1; why += " 单日%+.0f%%降一档" % vix_chg_pct
    return tiers[i], why


# ---------------- Kelly(只显示) ----------------
def kelly_fraction(hits, misses, avg_win=None, avg_loss=None):
    """f* = p − q/b;b 缺时按 1;样本 <20 → quarter,≥20 → half;f* ≤ 0 → 0。返回 (分数, 说明)。"""
    n = hits + misses
    if n == 0:
        return 0.0, "无复盘样本,不建仓位参考"
    p = hits / n
    b = (avg_win / avg_loss) if (avg_win and avg_loss) else 1.0
    f = p - (1 - p) / b
    mult, label = (0.25, "quarter") if n < 20 else (0.5, "half")
    frac = max(0.0, f * mult)
    return round(frac, 3), "命中 %d/%d p=%.2f b=%.2f f*=%.2f → %s-Kelly %.1f%%" % (hits, n, p, b, f, label, frac * 100)
