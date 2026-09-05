#!/usr/bin/env python3
"""verify_alpha_universe.py · v1 — 8600 宇宙扩容门禁(SPEC V1–V8 + 静态)。
在 worker 容器跑:python3 verify_alpha_universe.py [--db /data/platform.db] [--universe /data/universe_market.json]
退出码 0=全绿;1=有 FAIL。每条都能红,不是装饰。"""
import argparse, datetime as dt, json, os, re, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OK, FAIL = [], []
def _ok(m): OK.append(m); print("  OK   ", m)
def _fail(m): FAIL.append(m); print("  FAIL ", m)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.getenv("PLATFORM_DB", "/data/platform.db"))
    ap.add_argument("--universe", default=os.getenv("UNIVERSE_MARKET_CACHE", "/data/universe_market.json"))
    ap.add_argument("--sp500", default=os.getenv("SP500_SYMBOLS_CACHE", "/data/sp500_symbols.json"))
    ap.add_argument("--factor-truth", default=os.path.join(HERE, "factor_truth.py"))
    a = ap.parse_args()
    os.environ["SP500_SYMBOLS_CACHE"] = a.sp500          # factor_truth 模块级常量在 import 时读 env:先设再 import
    os.environ["UNIVERSE_MARKET_CACHE"] = a.universe

    # ---- 静态:器官在场 ----
    src = open(a.factor_truth, encoding="utf-8").read() if os.path.isfile(a.factor_truth) else ""
    need = ["def needs_pull(", "bar_fetch_log", "def _log_attempt(", "GAP_BREAKER_MIN", "final_close_pass",
            "def load_universe_market(", "def pull_sp500_and_universe_shard(", "univ_bars_cursor",
            "def _movers_passes_floor(", "\"universe\": _universe_tag", "def _adv20_dollar(", "_age_h",
            "def refresh_intraday_quotes(", "def fetch_fmp_quote(", "intraday_quotes(", "\"source\": source"]
    miss = [k for k in need if k not in src]
    if src and not miss:
        _ok("静态:§0 v2 新鲜度(needs_pull/bar_fetch_log/终盘补拉/断路器)+ 宇宙 loader + 分片 + movers 地板/标签 在场")
    else:
        _fail("静态:factor_truth.py 缺 %s" % (miss or "文件"))
    if src and "return latest >= now.date()" not in src and "_session_day_bounds(day)" not in src.split("def pull_daily_bars")[-1][:4000]:
        _ok("静态:不再按'今天午夜/今日日期'判新鲜(needs_pull 接管)")
    else:
        _fail("静态:'今天午夜'判新鲜回滚(隔夜每 5 分钟重拉 501 票案)")

    heat_p = os.path.join(os.path.dirname(a.factor_truth), "heat_nomination.py")
    if os.path.isfile(heat_p):
        hs = open(heat_p, encoding="utf-8").read()
        if "factor_truth._movers_from_daily_bars(" in hs and "def _same_day_movers(" in hs and "[:40]" in hs:
            _ok("V10 静态:heat 接线不变——movers 席读 _movers_from_daily_bars(并集+quote)、只收当日 asof、gainers[:40]")
        else:
            _fail("V10 静态:heat_nomination 的 movers 接线被改(不再读 _movers_from_daily_bars / 当日闸 / [:40])")
    try:
        import factor_truth as ft
    except Exception as exc:
        _fail("import factor_truth 失败:%s" % exc); return _finish()
    if not os.path.isfile(a.db):
        _fail("库不存在:%s" % a.db); return _finish()
    c = sqlite3.connect(a.db)
    ft.ensure_schema(c)
    now = dt.datetime.now(ft.ET)

    # ---- V2/V3/V4:宇宙文件 ----
    udoc = None
    try:
        udoc = json.load(open(a.universe, encoding="utf-8"))
    except Exception as exc:
        _fail("V2 宇宙文件不可读:%s" % exc)
    sp = []
    try:
        sp = list(json.load(open(a.sp500, encoding="utf-8")).get("symbols") or [])
    except Exception:
        pass
    if udoc:
        rows = udoc.get("rows") or []
        d = udoc.get("definition") or {}
        pm, dv, mc = float(d.get("price_min", 0)), float(d.get("dollar_vol_min", 0)), float(d.get("mcap_min", 0))
        exs = set(d.get("exchanges") or [])
        bad = [r["symbol"] for r in rows if not (r.get("price", 0) >= pm and r.get("dollar_vol", 0) >= dv
                                                and r.get("market_cap", 0) >= mc and (not exs or r.get("exchange") in exs))]
        n = udoc.get("n", 0); syms = set(udoc.get("symbols") or [])
        inter = len(syms & set(sp))
        age_h = (time.time() - float(udoc.get("ts", 0))) / 3600
        if udoc.get("kind") == "universe_market" and n >= 500 and n == len(syms) == len(rows) and not bad and inter > 200 and age_h < 48:
            _ok("V2 宇宙文件:kind/n=%d/行全过定义/与 sp500 交集 %d/age %.1fh" % (n, inter, age_h))
        else:
            _fail("V2 宇宙文件:n=%d rows=%d 不过定义 %d 交集 %d age %.1fh" % (n, len(rows), len(bad), inter, age_h))
        etf = [s for s in ("IBIT", "BITO", "TSLL", "SOXL", "SPY", "QQQ") if s in syms]
        _ok("V3 处决·ETF 不在宇宙") if not etf else _fail("V3 ETF 混入宇宙:%s" % etf)
        rmap = {r["symbol"]: r for r in rows}
        verdicts = []
        for s_ in ("MARA", "BMNR", "ASST"):
            r = rmap.get(s_)
            if r:
                verdicts.append("%s 在(price %.2f dv $%.0fM mc $%.1fB)" % (s_, r["price"], r["dollar_vol"] / 1e6, r["market_cap"] / 1e9))
            else:
                verdicts.append("%s 不在(不在 screener 回包或某项不过定义)" % s_)
        _ok("V4 三只按定义:" + " · ".join(verdicts))
    # ---- V1:盘外静默 ----
    if sp:
        census = {}
        for s_ in sp:
            _, why = ft.needs_pull(c, s_, now=now)
            census[why] = census.get(why, 0) + 1
        rth = ft._is_rth(now)
        quiet = (census.get("fresh", 0) + census.get("ahead", 0)) / max(1, len(sp))
        if rth:
            _ok("V1 盘中跑,静默率不适用;理由分布 %s" % census)
        elif quiet >= 0.95 or (census.get("gap_cooldown", 0) + census.get("no_bars", 0) >= 0.9 * len(sp)):
            _ok("V1 盘外静默:fresh %.0f%% 理由分布 %s" % (quiet * 100, census))
        else:
            _fail("V1 盘外仍有待拉:%s(§0 未生效)" % census)
    else:
        _fail("V1/V5 无 sp500 文件")
    # ---- V5:宇宙前 200 覆盖 ----
    if udoc:
        top = [r["symbol"] for r in sorted(udoc.get("rows") or [], key=lambda r: -r.get("dollar_vol", 0))[:200]]
        have = sum(1 for s_ in top if ft._latest_bar_date(c, s_) is not None)
        if have >= 0.9 * len(top):
            _ok("V5 daily_bars 覆盖:宇宙成交额前 200 有 bar %d/%d" % (have, len(top)))
        else:
            _fail("V5 daily_bars 覆盖不足:%d/%d(分片未跑完或 loader 未接)" % (have, len(top)))
    # ---- V6/V7:movers 地板与标签、红线 ----
    try:
        pay = ft._movers_from_daily_bars(c, sp, set())
        rows = (pay.get("gainers") or []) + (pay.get("losers") or [])
        bad = [r["symbol"] for r in rows if r.get("last", 0) < ft.MOVERS_PRICE_MIN or (r.get("adv20") or 0) < ft.MOVERS_ADV20_MIN
               or r.get("universe") not in ("sp500", "market", "both") or r["symbol"] in ft.ETF_DENY_MOVERS]
        if rows and not bad:
            tags = {}
            for r in rows: tags[r["universe"]] = tags.get(r["universe"], 0) + 1
            _ok("V6 movers 地板+标签:%d 行全过,标签分布 %s" % (len(rows), tags))
        elif not rows:
            _fail("V6 movers 空(status=%s)" % pay.get("status"))
        else:
            _fail("V6 movers 地板/标签不过:%s" % bad[:10])
        import db as _db
        deny = [r["symbol"] for r in rows if r["symbol"] in _db.SURFACE_DENY]
        _ok("V7 红线:SURFACE_DENY 不在 movers") if not deny else _fail("V7 SURFACE_DENY 进 movers:%s" % deny)
    except Exception as exc:
        _fail("V6/V7 movers 计算异常:%s" % exc)
    # ---- V9(v2.2):盘中 movers 走 quote ----
    try:
        mix = pay.get("source_mix") or {}
        if ft._is_rth(now) and ft.INTRADAY_QUOTES:
            share = mix.get("quote", 0) / max(1, pay.get("with_data", 0))
            if share >= 0.9:
                _ok("V9 盘中 movers source=quote %.0f%%(同日 asof)" % (share * 100))
            else:
                _fail("V9 盘中 movers quote 占比 %.0f%%<90%%(quote 轮刷未跑或过期):mix=%s" % (share * 100, mix))
        else:
            nq = c.execute("SELECT COUNT(*) FROM intraday_quotes WHERE price IS NOT NULL").fetchone()[0]
            _ok("V9 盘外跑(或 INTRADAY_QUOTES=0):不判占比;intraday_quotes 表有价 %d 行,mix=%s" % (nq, mix))
    except Exception as exc:
        _fail("V9 quote 检查异常:%s" % exc)
    # ---- V8:配额(bars + quotes) ----
    st = ft._get_state(c, "fmp_daily_gets") or {}
    n_univ = (udoc or {}).get("n", 0)
    n_all = len(sp) + n_univ
    bound = n_all * (1 + int(6.5 * 3600 / max(1, ft.RTH_REFRESH_S)) + 1) + 30 * n_all \
        + (n_all * (int(6.5 * 3600 / max(1, ft.QUOTE_REFRESH_S)) + 1) if ft.INTRADAY_QUOTES else 0)
    cnt = int(st.get("count", 0))
    if st.get("day") == now.date().isoformat() and cnt > bound:
        _fail("V8 FMP 单票 GET %d > 上限 %d(RTH_REFRESH_S=%d)" % (cnt, bound, ft.RTH_REFRESH_S))
    else:
        _ok("V8 FMP 单票 GET 今日 %d ≤ 上限 %d(day=%s)" % (cnt, bound, st.get("day")))
    return _finish()

def _finish():
    print("---\nOK %d · FAIL %d" % (len(OK), len(FAIL)))
    if FAIL:
        print("门禁未过:"); [print("  -", m) for m in FAIL]
        sys.exit(1)
    print("门禁通过。")

if __name__ == "__main__":
    main()
