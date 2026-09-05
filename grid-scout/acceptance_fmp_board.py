#!/usr/bin/env python3
"""acceptance_fmp_board.py · v1(2026-08-25,Lyra:"测出来的票不在 FMP top mover 榜,不收")
在 grid-scout 目录跑,读当日 raw(FMP 真实回包)与当班 brief json,逐卡对榜。零推断,只对数据。
  python3 acceptance_fmp_board.py --date 2026-08-25 --shift earnings
退出码 0=全过;1=有卡不在榜/形态错配/名单序与实测不符。"""
import argparse, glob, json, os, re, sys

OUT = os.path.dirname(os.path.abspath(__file__))


def load_raw(date):
    paths = sorted(glob.glob(os.path.join(OUT, "raw", date + "*.json")))
    if not paths:
        sys.exit("raw 缺失:%s" % date)
    raws = [json.load(open(p, encoding="utf-8")) for p in paths]
    return raws[-1], paths[-1]        # 当日最后一次采集 = 财报班/晚班用的那份


def boards(raw):
    g, a, a_up = set(), set(), set()
    for src in raw.get("results", raw.get("sources", [])):
        if src.get("source") == "market_movers":
            for it in src.get("items") or []:
                if it.get("side") == "gainers":
                    g.add(str(it.get("symbol")).upper())
        if src.get("source") == "most_active":
            for it in src.get("items") or []:
                a.add(str(it.get("symbol")).upper())
                if (it.get("chg_pct") or 0) > 0:
                    a_up.add(str(it.get("symbol")).upper())
    return g, a, a_up


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--shift", default="earnings", choices=["morning", "midday", "earnings", "evening"])
    a = ap.parse_args()
    raw, rp = load_raw(a.date)
    g, act, act_up = boards(raw)
    trend = set()
    for tp in sorted(glob.glob(os.path.join(OUT, "state", "trend_board-*.json"))):   # v3.28:自算趋势榜也是"钱的榜"
        try:
            trend |= {r.get("symbol") for r in (json.load(open(tp, encoding="utf-8")).get("board") or [])}
        except Exception:
            pass
    bp = os.path.join(OUT, "briefs", "%s-%s.json" % (a.date, a.shift))
    if not os.path.exists(bp):
        sys.exit("brief 缺失:%s" % bp)
    doc = json.load(open(bp, encoding="utf-8"))
    eng, ds = doc.get("_engine") or {}, doc.get("ds") or {}
    fails, oks = [], []
    print("raw=%s  FMP 涨幅榜 %d 只 · 最活跃 %d 只(收涨 %d) · 自算趋势榜 %d 只" % (os.path.basename(rp), len(g), len(act), len(act_up), len(trend)))
    if not g and not act:
        fails.append("FMP 两榜为空——源失败,本班一切候选无资金确认")
    # 1) 已发布的候选卡(非空、非对冲)逐卡对榜
    for c in ds.get("candidates") or []:
        if not isinstance(c, dict) or c.get("empty"):
            continue
        t = str(c.get("ticker") or "").upper()
        if not re.fullmatch(r"[A-Z]{1,5}", t):
            fails.append("S%s 非单一代码 '%s'" % (c.get("slot"), t)); continue
        note = "%s %s" % (c.get("note") or "", (c.get("strategy") or {}).get("note") or "")
        tag = "预排" if "明晨预排" in note else ("初筛" if "AMC 初筛观察" in note else "实卡")
        on = ("涨幅榜" if t in g else "") + ("+最活跃收涨" if t in act_up else ("+最活跃(收跌)" if t in act else "")) + ("+趋势榜" if t in trend else "")
        tc = c.get("tape_check") or {}
        line = "S%s %s %s %s | 榜:%s | tape 日%s loc%s" % (c.get("slot"), t, str(c.get("direction") or "").upper(), tag,
                                                            on or "不在榜", tc.get("chg_pct"), tc.get("close_loc"))
        bad = []
        if str(c.get("direction") or "").lower() == "call" and tag == "实卡" and t not in g and t not in act_up and t not in trend:
            bad.append("call 实卡不在 FMP 涨幅榜/最活跃收涨/自算趋势榜")
        try:
            if str(c.get("direction") or "").lower() == "call" and tc.get("chg_pct") is not None and tc.get("close_loc") is not None \
                    and float(tc["chg_pct"]) <= -1.0 and float(tc["close_loc"]) < 0.5:
                bad.append("call 卡尾盘弱势收低(引擎实测)")
        except (TypeError, ValueError):
            pass
        (fails if bad else oks).append(line + ((" ← " + ";".join(bad)) if bad else ""))
    # 2) 引擎名单/池:前三是否在榜(池行必须;财报名单只报不判)
    pool = eng.get("candidate_pool") or []
    for p in pool[:3]:
        s_ = p.get("symbol")
        if s_ in g or s_ in act_up or s_ in trend:
            oks.append("池#%d %s 在榜(%s)" % (pool.index(p) + 1, s_, "涨幅榜" if s_ in g else ("最活跃收涨" if s_ in act_up else "趋势榜")))
        else:
            fails.append("池#%d %s 不在 FMP 涨幅榜/最活跃收涨/趋势榜(池是七眼并集,前三不在榜=眼有假)" % (pool.index(p) + 1, s_))
    for k in ("amc_tonight", "bmo_tomorrow"):
        rows = eng.get(k) or []
        if rows:
            print("%s(按 earn_score):%s" % (k, " · ".join("%s(%s%s)" % (r.get("symbol"), r.get("earn_score"), ",榜" if r.get("fmp_board") else "") for r in rows[:6])))
    for m in oks:
        print("  OK   ", m)
    for m in fails:
        print("  FAIL ", m)
    print("---\nOK %d · FAIL %d" % (len(oks), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
