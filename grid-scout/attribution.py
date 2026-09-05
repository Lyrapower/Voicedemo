"""attribution.py · Scout v3.31 反馈回路(2026-08-26,Lyra:"行动呢?主动改进呢?")

三件此前不存在的东西:
1. 因子归因账本 `state/attrib.jsonl`:每班把 候选池前 N + 发出的卡 的六因子子分/总分/视角/当时价 落一行;
   晚班用当日收盘(T+0 视角)与次日收盘(swing 视角)结算 outcome。
2. 因子表现表 `factor_report()`:近 N 日每个因子子分与 outcome 的 Spearman 秩相关(IC)、按总分分桶的命中率——
   权重是不是拍脑袋,这张表说了算;改权重由 Lyra 看表拍。
3. 数据自检 `data_selfcheck()`:池前 K 名的最新日线用第二源(Alpaca)复核,收盘偏差 > 阈值响亮报(INTU 8-25 部分 bar 案会被它抓到)。

期权结算 `option_pnl()` 在 fetchers.theta_option_mid_at() 可用时把卡按入场/出场时刻的 ATM 中价结算(0DTE 卡的真实盈亏),
不可用时 pnl=None 且原因入行,不装数。
"""
from __future__ import annotations

import datetime
import json
import math
import os

FACTOR_KEYS = ("F1_money", "F2_trend", "F3_tape", "F4_event", "F5_options")


def _path(out_dir):
    return os.path.join(out_dir, "state", "attrib.jsonl")


def log_rows(out_dir, date, shift, rows):
    """rows: [{symbol, role('card'|'pool'), rank, score, view, subs, price, direction, entry_window, exit_window, slot}]。追加写。"""
    p = _path(out_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            rec = dict(r)
            rec.update({"date": date, "shift": shift, "logged_ts": datetime.datetime.now().astimezone().isoformat(),
                        "outcome_t0": None, "outcome_next": None, "opt_pnl": None, "opt_note": None})
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_rows(out_dir, days=40):
    p = _path(out_dir)
    if not os.path.exists(p):
        return []
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    out = []
    for line in open(p, encoding="utf-8"):
        try:
            r = json.loads(line)
            if r.get("date", "") >= cutoff:
                out.append(r)
        except Exception:
            continue
    return out


def _rewrite(out_dir, rows_all):
    p = _path(out_dir)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows_all:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def resolve(out_dir, date, close_by_sym, next_close_by_sym=None, opt_fn=None):
    """晚班结算:date 当日行的 outcome_t0 = 收盘/当时价 − 1(%);date 前一交易日行的 outcome_next = 次日收盘/当时价 − 1。
    opt_fn(row) → (pnl_pct, note) 可选(Theta 期权中价);返回结算条数。"""
    p = _path(out_dir)
    if not os.path.exists(p):
        return 0
    rows_all = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    n = 0
    for r in rows_all:
        px = r.get("price")
        if not px:
            continue
        if r.get("date") == date and r.get("outcome_t0") is None and r["symbol"] in close_by_sym:
            r["outcome_t0"] = round((close_by_sym[r["symbol"]] / px - 1) * 100, 3); n += 1
            if opt_fn and r.get("role") == "card" and r.get("opt_pnl") is None:
                try:
                    pnl, note = opt_fn(r)
                except Exception as exc:
                    pnl, note = None, "opt_fn 异常:%s" % str(exc)[:80]
                r["opt_pnl"], r["opt_note"] = pnl, note
        if next_close_by_sym and r.get("date") < date and r.get("outcome_next") is None and r["symbol"] in next_close_by_sym:
            r["outcome_next"] = round((next_close_by_sym[r["symbol"]] / px - 1) * 100, 3); n += 1
    _rewrite(out_dir, rows_all)
    return n


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x, y):
    if len(x) < 5:
        return None
    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx)); vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return round(cov / (vx * vy), 3) if vx and vy else None


def factor_report(out_dir, days=20):
    """→ {"n": 样本, "ic": {F: IC 或 None}, "buckets": [{"range", "n", "hit_rate", "avg"}], "cards": {"n", "hit_rate", "avg", "opt_n", "opt_avg"}}
    outcome 口径:t0 视角行用 outcome_t0,swing 视角行用 outcome_next(缺则用 t0)。"""
    rows = [r for r in load_rows(out_dir, days) if (r.get("outcome_next") is not None or r.get("outcome_t0") is not None)]
    def oc(r):
        if r.get("view") == "t0":
            return r.get("outcome_t0") if r.get("outcome_t0") is not None else r.get("outcome_next")
        return r.get("outcome_next") if r.get("outcome_next") is not None else r.get("outcome_t0")
    ys = [oc(r) for r in rows]
    ic = {}
    for k in FACTOR_KEYS:
        xs, yy = [], []
        for r, y in zip(rows, ys):
            v = (r.get("subs") or {}).get(k)
            if v is not None and y is not None:
                xs.append(v); yy.append(y)
        ic[k] = {"ic": spearman(xs, yy), "n": len(xs)}
    xs, yy = [], []
    for r, y in zip(rows, ys):
        if r.get("score") is not None and y is not None:
            xs.append(r["score"]); yy.append(y)
    ic["score"] = {"ic": spearman(xs, yy), "n": len(xs)}
    buckets = []
    for lo, hi in ((0, 45), (45, 60), (60, 75), (75, 101)):
        sel = [y for r, y in zip(rows, ys) if r.get("score") is not None and y is not None and lo <= r["score"] < hi]
        if sel:
            buckets.append({"range": "%d-%d" % (lo, hi - 1), "n": len(sel), "hit_rate": round(sum(1 for y in sel if y > 0) / len(sel), 2),
                            "avg": round(sum(sel) / len(sel), 2)})
    cards = [r for r in rows if r.get("role") == "card"]
    cy = [oc(r) for r in cards if oc(r) is not None]
    opt = [r["opt_pnl"] for r in cards if r.get("opt_pnl") is not None]
    return {"n": len(rows), "ic": ic, "buckets": buckets,
            "cards": {"n": len(cy), "hit_rate": (round(sum(1 for y in cy if y > 0) / len(cy), 2) if cy else None),
                      "avg": (round(sum(cy) / len(cy), 2) if cy else None),
                      "opt_n": len(opt), "opt_avg": (round(sum(opt) / len(opt), 1) if opt else None)}}


def report_line(rep):
    if not rep or not rep.get("n"):
        return "无已结算样本(账本从 v3.31 起记,首晚开始结算)"
    ics = " ".join("%s %s(n%d)" % (k[:2] if k != "score" else "总", ("%+.2f" % v["ic"]) if v["ic"] is not None else "-", v["n"]) for k, v in rep["ic"].items())
    bk = " ".join("[%s]%d票 命中%.0f%% 均%+.1f%%" % (b["range"], b["n"], b["hit_rate"] * 100, b["avg"]) for b in rep["buckets"])
    c = rep["cards"]
    cl = ("卡 %d 张 命中%s 均%s%%" % (c["n"], ("%.0f%%" % (c["hit_rate"] * 100)) if c["hit_rate"] is not None else "-", c["avg"])
          + ((" 期权中价 %d 张 均%+.1f%%" % (c["opt_n"], c["opt_avg"])) if c["opt_n"] else " 期权中价未结算"))
    return "样本 %d · IC %s · 分桶 %s · %s" % (rep["n"], ics, bk, cl)


def data_selfcheck(symbols, primary_close_by_sym, secondary_fn, tol_pct=0.5):
    """用第二源复核收盘:secondary_fn(sym) → (date, close) 或 None。返回 {"checked", "mismatch": [...], "unavailable"}。"""
    out = {"checked": 0, "mismatch": [], "unavailable": 0}
    for s in symbols:
        p = primary_close_by_sym.get(s)
        if p is None:
            continue
        try:
            sec = secondary_fn(s)
        except Exception:
            sec = None
        if not sec or not sec[1]:
            out["unavailable"] += 1
            continue
        out["checked"] += 1
        dev = abs(sec[1] / p - 1) * 100
        if dev > tol_pct:
            out["mismatch"].append({"symbol": s, "primary": p, "secondary": sec[1], "secondary_date": sec[0], "dev_pct": round(dev, 2)})
    return out
