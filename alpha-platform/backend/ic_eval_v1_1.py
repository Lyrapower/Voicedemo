"""ic_eval v1.1 · 横截面 IC 评估器(2026-09-02,砥;v1.1 加 evaluate_frame:直接吃 factor_sandbox 的 work 表,不再执行因子代码)

对 daily_bars(ts,symbol,o,h,l,c,v) 算:每个交易日横截面 Spearman IC(因子值秩 vs 未来 h 日收益秩),
再汇总 ic_mean / ic_std / ic_t / IR / 命中率 / 20 日滚动。零新依赖(sqlite3 + 标准库)。
结果可直接写进 factor_lineage_v1 的 evals(settlement 记 "close_to_close"——这是日线口径,不是期权中价;
Scout/T+0 的中价结算 IC 另算,别混)。

因子接口:factor(bars: dict[symbol -> list[(date, o, h, l, c, v)]]) -> dict[(date, symbol) -> float]
内置因子(仅供起跑与处决案):mom_5 / rev_1 / vol_20 / oracle_h(未来收益本身,IC 应≈1)/ noise(随机,IC 应≈0)

CLI:
  python3 ic_eval_v1.py selftest
  python3 ic_eval_v1.py run --db <daily_bars.db> --factor mom_5 --horizon 5 [--start 2026-06-01 --end 2026-08-31] [--lineage-id 12]
  python3 ic_eval_v1.py list-factors
ts 列:unix 秒(REAL/INTEGER)或 'YYYY-MM-DD' 文本都认。
"""
from __future__ import annotations
import argparse, json, math, os, random, sqlite3, sys, time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

MIN_NAMES = int(os.environ.get("IC_MIN_NAMES", "20"))   # 每日横截面最少标的数
MIN_N = int(os.environ.get("FACTOR_MIN_N", "60"))         # 与 lineage 同一口径
ROLL = 20

Bar = tuple[str, float, float, float, float, float]   # (date, o, h, l, c, v)


# ---------- 数据 ----------

def _to_date(ts) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    s = str(ts)
    return s[:10]


def _load_universe(path: str) -> list[str]:
    """读 universe json({symbols:[...]} 或 [...])→ 大写 symbol 列表。"""
    data = json.load(open(path))
    syms = data.get("symbols", data) if isinstance(data, dict) else data
    return [str(s).strip().upper() for s in syms if str(s).strip()]


def load_bars(db_path: str, start: str | None = None, end: str | None = None,
              symbols: list[str] | None = None, exclude_src: tuple[str, ...] = ()) -> dict[str, list[Bar]]:
    con = sqlite3.connect(db_path)
    q = "SELECT ts,symbol,o,h,l,c,v FROM daily_bars"
    args: list = []
    clauses: list[str] = []
    if symbols:
        clauses.append("symbol IN (%s)" % ",".join("?" * len(symbols))); args += symbols
    if exclude_src:
        clauses.append("(" + " AND ".join("IFNULL(src,'') != ?" for _ in exclude_src) + ")")
        args += list(exclude_src)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY symbol, ts"
    out: dict[str, list[Bar]] = defaultdict(list)
    for ts, sym, o, h, l, c, v in con.execute(q, args):
        d = _to_date(ts)
        if start and d < start: continue
        if end and d > end: continue
        if c is None or c <= 0: continue
        out[sym].append((d, o, h, l, float(c), v or 0.0))
    con.close()
    return dict(out)


# ---------- 统计 ----------

def _rank(xs: list[float]) -> list[float]:
    """平均秩(处理并列)。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) != len(b) or len(a) < 3:
        return None
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra); vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None          # 常数因子/常数收益:当日无信息,跳过
    return cov / math.sqrt(va * vb)


def forward_returns(bars: dict[str, list[Bar]], horizon: int) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for sym, rows in bars.items():
        for i in range(len(rows) - horizon):
            c0, c1 = rows[i][4], rows[i + horizon][4]
            out[(rows[i][0], sym)] = c1 / c0 - 1.0
    return out


def daily_ic(factor_vals: dict[tuple[str, str], float], fwd: dict[tuple[str, str], float]) -> list[tuple[str, float, int]]:
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for key, f in factor_vals.items():
        if key in fwd and f is not None and not math.isnan(f):
            by_date[key[0]].append((f, fwd[key]))
    rows = []
    for d in sorted(by_date):
        pairs = by_date[d]
        if len(pairs) < MIN_NAMES:
            continue
        ic = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        if ic is not None:
            rows.append((d, ic, len(pairs)))
    return rows


def summarize(ics: list[tuple[str, float, int]]) -> dict:
    n = len(ics)
    if n == 0:
        return {"n_obs": 0, "ic_mean": None, "ic_std": None, "ic_t": None, "ir": None, "hit": None, "roll20": []}
    vals = [x[1] for x in ics]
    mean = sum(vals) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    t = mean / (std / math.sqrt(n)) if std > 0 else (math.copysign(1e6, mean) if mean != 0 else None)   # 零方差:方向确定,t=±1e6(不用 inf,sqlite 存不住)
    roll = [(ics[i][0], sum(vals[i - ROLL + 1:i + 1]) / ROLL) for i in range(ROLL - 1, n)]
    return {"n_obs": n, "ic_mean": mean, "ic_std": std, "ic_t": t, "ir": (mean / std if std > 0 else None),
            "hit": sum(1 for v in vals if v > 0) / n, "roll20": roll,
            "first": ics[0][0], "last": ics[-1][0], "names_avg": sum(x[2] for x in ics) / n}


# ---------- 与 factor_sandbox 的适配(接入点 3) ----------

def evaluate_frame(work, horizon: int = 5, ts_col: str = "ts", symbol_col: str = "symbol",
                   close_col: str = "c", fac_col: str = "fac") -> dict:
    """吃 factor_sandbox.run_factor_review 内部那张 work 表(ts, symbol, c, fac …),不再执行任何因子代码。
    LLM 代码只在沙箱里跑过一次;这里只拿它算好的值。ts 为 unix 秒或日期文本都认。"""
    bars: dict[str, list[Bar]] = defaultdict(list)
    fv: dict[tuple[str, str], float] = {}
    rows = work[[ts_col, symbol_col, close_col, fac_col]].itertuples(index=False, name=None)
    for ts, sym, c, fac in rows:
        if c is None or c <= 0:
            continue
        d = _to_date(ts)
        bars[sym].append((d, None, None, None, float(c), 0.0))
        if fac is not None and fac == fac:      # 非 NaN
            fv[(d, sym)] = float(fac)
    for sym in bars:
        bars[sym].sort(key=lambda r: r[0])
    fwd = forward_returns(dict(bars), horizon)
    ics = daily_ic(fv, fwd)
    s = summarize(ics); s["horizon"] = horizon; s["daily"] = ics
    return s


# ---------- 内置因子 ----------

def _f_mom(k: int) -> Callable:
    def f(bars):
        out = {}
        for sym, rows in bars.items():
            for i in range(k, len(rows)):
                out[(rows[i][0], sym)] = rows[i][4] / rows[i - k][4] - 1.0
        return out
    return f


def _f_rev1(bars):
    out = {}
    for sym, rows in bars.items():
        for i in range(1, len(rows)):
            out[(rows[i][0], sym)] = -(rows[i][4] / rows[i - 1][4] - 1.0)
    return out


def _f_vol(k: int) -> Callable:
    def f(bars):
        out = {}
        for sym, rows in bars.items():
            rets = [rows[i][4] / rows[i - 1][4] - 1.0 for i in range(1, len(rows))]
            for i in range(k, len(rets)):
                w = rets[i - k:i]
                m = sum(w) / k
                out[(rows[i + 1][0], sym)] = -math.sqrt(sum((r - m) ** 2 for r in w) / k)   # 低波动为正
        return out
    return f


def _f_oracle(h: int) -> Callable:
    """未来 h 日收益本身——处决案专用,IC 必须≈1。生产禁用。"""
    def f(bars):
        return forward_returns(bars, h)
    return f


def _f_noise(bars):
    rng = random.Random(7)
    return {(r[0], s): rng.random() for s, rows in bars.items() for r in rows}


FACTORS: dict[str, Callable] = {
    "mom_5": _f_mom(5), "mom_20": _f_mom(20), "rev_1": _f_rev1, "vol_20": _f_vol(20),
    "noise": _f_noise,
}
for _h in (1, 5):
    FACTORS[f"oracle_{_h}"] = _f_oracle(_h)


# ---------- 主流程 ----------

def evaluate(bars: dict[str, list[Bar]], factor: Callable, horizon: int) -> dict:
    fv = factor(bars)
    fwd = forward_returns(bars, horizon)
    ics = daily_ic(fv, fwd)
    s = summarize(ics)
    s["horizon"] = horizon
    s["daily"] = ics
    return s


def evaluate_regime(bars: dict[str, list[Bar]], factor: Callable, horizon: int,
                    labels: dict[str, str], min_n: int | None = None) -> dict:
    """Per-bucket IC. min_n defaults to MIN_N; thicker sample does not lower the gate."""
    import regime as RG
    min_n = MIN_N if min_n is None else min_n
    full = evaluate(bars, factor, horizon)
    fv = factor(bars)
    fwd = forward_returns(bars, horizon)
    by_b: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    ics = daily_ic(fv, fwd)
    for d, ic, n in ics:
        lab = labels.get(d)
        if not lab or lab == "data_short":
            continue
        by_b[lab].append((d, ic, n))
    buckets = {}
    for lab, rows in sorted(by_b.items()):
        s = summarize(rows)
        s["horizon"] = horizon
        s["daily"] = rows
        mid = max(1, len(rows) // 2)
        s["half_a"] = summarize(rows[:mid])
        s["half_b"] = summarize(rows[mid:])
        v, why = RG.bucket_verdict(
            s["n_obs"], s["ic_mean"], s["ic_t"], rows,
            min_n=min_n, full_mean=full.get("ic_mean"), bucket=lab,
        )
        s["verdict"] = v
        s["reason"] = why
        buckets[lab] = s
    return {"full": full, "buckets": buckets, "min_n": min_n}


def write_lineage(summary: dict, lineage_id: int, receipt_path: str, verdict: str, reason: str) -> int | None:
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import factor_lineage_v1_1 as FL
    except Exception as e:  # noqa
        print(f"[ic_eval] lineage 模块不可用,未写入:{e}")
        return None
    return FL.record_eval(lineage_id, summary.get("first", ""), summary.get("last", ""), f"{summary['horizon']}d",
                          summary["n_obs"], summary["ic_mean"], summary["ic_std"], "close_to_close",
                          None, receipt_path, verdict, reason)


def auto_verdict(s: dict) -> tuple[str, str]:
    if s["n_obs"] < MIN_N:
        return "insufficient", f"n_obs={s['n_obs']}<{MIN_N}"
    if s["ic_t"] is None:
        return "watch", "ic 恒为 0"
    if s["ic_mean"] > 0 and s["ic_t"] >= 2.0:
        return "keep", f"ic={s['ic_mean']:.4f} t={s['ic_t']:.2f} hit={s['hit']:.2f}"
    if s["ic_mean"] < 0 and s["ic_t"] <= -2.0:
        return "watch", f"反向显著 ic={s['ic_mean']:.4f} t={s['ic_t']:.2f}:改符号后再评,不自动翻"
    return "reject", f"不显著 ic={s['ic_mean']:.4f} t={s['ic_t']:.2f}"


# ---------- 处决案 ----------

def _synthetic_db(path: str, n_sym: int = 60, n_days: int = 200, seed: int = 1) -> None:
    rng = random.Random(seed)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE daily_bars(ts REAL, symbol TEXT, o REAL, h REAL, l REAL, c REAL, v REAL)")
    t0 = 1_750_000_000
    for i in range(n_sym):
        p = 100.0 * (1 + rng.random())
        for d in range(n_days):
            r = rng.gauss(0.0, 0.02)
            p *= (1 + r)
            con.execute("INSERT INTO daily_bars VALUES(?,?,?,?,?,?,?)",
                        (t0 + d * 86400, f"S{i:03d}", p, p * 1.01, p * 0.99, p, 1e6))
    con.commit(); con.close()


def selftest() -> int:
    import tempfile
    fails: list[str] = []
    must = lambda c, m: (None if c else fails.append(m))
    tmp = tempfile.mkdtemp(); db = os.path.join(tmp, "bars.db"); _synthetic_db(db)
    bars = load_bars(db)
    # 1 oracle:IC≈1,t 极大
    s = evaluate(bars, FACTORS["oracle_5"], 5)
    must(s["n_obs"] >= MIN_N and s["ic_mean"] > 0.95, f"1 oracle IC 应≈1,得 {s['ic_mean']}")
    must(auto_verdict(s)[0] == "keep", "1 oracle 未判 keep")
    # 2 noise:|IC|<0.1,不显著 → reject
    s2 = evaluate(bars, FACTORS["noise"], 5)
    must(abs(s2["ic_mean"]) < 0.1 and abs(s2["ic_t"]) < 2.5, f"2 noise IC 应≈0,得 {s2['ic_mean']} t={s2['ic_t']}")
    must(auto_verdict(s2)[0] == "reject", "2 noise 未判 reject")
    # 3 样本不足 → insufficient
    s3 = evaluate(load_bars(db, start="2025-06-01", end="2025-07-15"), FACTORS["mom_5"], 5)
    must(auto_verdict(s3)[0] == "insufficient", f"3 短窗未判 insufficient(n={s3['n_obs']})")
    # 4 常数因子 → 当日跳过,n_obs=0
    s4 = evaluate(bars, lambda b: {(r[0], sy): 1.0 for sy, rows in b.items() for r in rows}, 5)
    must(s4["n_obs"] == 0, f"4 常数因子应无有效日,得 {s4['n_obs']}")
    # 5 并列秩:spearman([1,1,2],[1,2,3]) 有定义且为正
    r = spearman([1, 1, 2, 3], [1, 2, 3, 4]); must(r is not None and r > 0.8, f"5 并列秩错 {r}")
    # 6 反向因子:-oracle → 判 watch(不自动翻符号)
    s6 = evaluate(bars, lambda b: {k: -v for k, v in FACTORS["oracle_5"](b).items()}, 5)
    must(auto_verdict(s6)[0] == "watch", "6 反向显著未判 watch")
    # 7 ts 文本日期也认
    db2 = os.path.join(tmp, "bars_txt.db"); con = sqlite3.connect(db2)
    con.execute("CREATE TABLE daily_bars(ts TEXT, symbol TEXT, o REAL, h REAL, l REAL, c REAL, v REAL)")
    for i in range(30):
        con.execute("INSERT INTO daily_bars VALUES(?,?,?,?,?,?,?)", (f"2026-01-{i+1:02d}", "A", 1, 1, 1, 100 + i, 1))
    con.commit(); con.close()
    must(len(load_bars(db2)["A"]) == 30 and load_bars(db2)["A"][0][0] == "2026-01-01", "7 文本 ts 未认")
    # 8 写入 lineage(若模块在旁)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import factor_lineage_v1_1 as FL
        os.environ["FACTOR_LINEAGE_DB"] = os.path.join(tmp, "fl.db")
        fid = FL.propose("close/close[-5]-1", "mom_5", "manual", None, "selftest", "5 日动量")
        eid = write_lineage(s, fid, "selftest", *auto_verdict(s))
        must(eid is not None, "8 lineage 写入失败")
        row = FL.connect().execute("SELECT settlement,verdict FROM evals WHERE id=?", (eid,)).fetchone()
        must(row["settlement"] == "close_to_close" and row["verdict"] == "keep", "8 写入内容错")
    except ImportError:
        print("[selftest] factor_lineage_v1 不在旁,跳过 8")
    # 9 evaluate_frame 与 evaluate 同结果(pandas 在则验)
    try:
        import pandas as pd
        recs = []
        fvo = FACTORS["mom_5"](bars)
        for sym, rows in bars.items():
            for r in rows:
                recs.append({"ts": r[0], "symbol": sym, "c": r[4], "fac": fvo.get((r[0], sym))})
        s9 = evaluate_frame(pd.DataFrame(recs), 5)
        s9b = evaluate(bars, FACTORS["mom_5"], 5)
        must(s9["n_obs"] == s9b["n_obs"] and abs(s9["ic_mean"] - s9b["ic_mean"]) < 1e-12, f"9 frame 路径不一致 {s9['n_obs']}/{s9b['n_obs']}")
    except ImportError:
        print("[selftest] pandas 不在,跳过 9")
    if fails:
        print("SELFTEST FAIL"); [print(" -", f) for f in fails]; return 1
    print(f"SELFTEST PASS (oracle ic={s['ic_mean']:.3f} t={s['ic_t']:.1f} | noise ic={s2['ic_mean']:.3f} t={s2['ic_t']:.2f} | n={s['n_obs']} days, MIN_NAMES={MIN_NAMES}, MIN_N={MIN_N})")
    return 0


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["selftest", "run", "list-factors"])
    ap.add_argument("--db"); ap.add_argument("--factor"); ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--start"); ap.add_argument("--end"); ap.add_argument("--lineage-id", type=int)
    ap.add_argument("--receipt", default="")
    ap.add_argument("--universe", default=None, help="json 文件 {symbols:[...]} 或 [...];run 必填,不默认全表")
    ap.add_argument("--regime", default=None, choices=["trend", "breadth", "vol"],
                    help="分桶 IC;缺省则主路径不变")
    a = ap.parse_args(argv[1:])
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "list-factors":
        print("\n".join(sorted(FACTORS))); return 0
    if not a.db or not a.factor or a.factor not in FACTORS:
        print("需要 --db 与 --factor(见 list-factors)"); return 2
    if a.factor.startswith("oracle"):
        print("oracle_* 是处决案专用因子,禁用于生产评估"); return 2
    if not a.universe:
        print("--universe required (json 文件,不默认全表)"); return 2
    symbols = _load_universe(a.universe)
    t0 = time.time()
    need = list(dict.fromkeys(symbols + (["SPY"] if a.regime in ("trend", "vol", "breadth") else [])))
    excl = ("alpaca_iex",) if a.regime else ()
    bars = load_bars(a.db, a.start, a.end, symbols=need, exclude_src=excl)
    if a.regime:
        import regime as RG
        labels = RG.labels_for(a.regime, bars, universe=symbols)
        univ_bars = {s: bars[s] for s in symbols if s in bars}
        pack = evaluate_regime(univ_bars, FACTORS[a.factor], a.horizon, labels)
        print(json.dumps({
            "factor": a.factor, "horizon": a.horizon, "regime": a.regime, "min_n": pack["min_n"],
            "full": {k: pack["full"].get(k) for k in ("n_obs", "ic_mean", "ic_std", "ic_t")},
            "buckets": {
                lab: {
                    "n_obs": s["n_obs"], "ic_mean": s["ic_mean"], "ic_t": s["ic_t"],
                    "half_a": s["half_a"].get("ic_mean"), "half_b": s["half_b"].get("ic_mean"),
                    "verdict": s["verdict"], "reason": s["reason"],
                } for lab, s in pack["buckets"].items()
            },
            "elapsed": round(time.time() - t0, 1),
        }, ensure_ascii=False, default=str))
        if a.lineage_id:
            _write_regime_evals(a.lineage_id, a.regime, pack, a.receipt)
        return 0
    s = evaluate(bars, FACTORS[a.factor], a.horizon)
    v, reason = auto_verdict(s)
    print(f"factor={a.factor} h={a.horizon} symbols={len(bars)} days={s['n_obs']} window={s.get('first')}..{s.get('last')}")
    print(f"ic_mean={s['ic_mean']} ic_std={s['ic_std']} ic_t={s['ic_t']} ir={s['ir']} hit={s['hit']} names_avg={s.get('names_avg')}")
    print(f"verdict={v} ({reason}) settlement=close_to_close elapsed={time.time()-t0:.1f}s")
    if s["roll20"]:
        print("roll20 tail:", " ".join(f"{d}:{x:+.3f}" for d, x in s["roll20"][-5:]))
    if a.lineage_id:
        eid = write_lineage(s, a.lineage_id, a.receipt, v, reason)
        print(f"lineage evals id={eid}")
    return 0


def _ensure_regime_cols(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(evals)")}
    if "regime" not in cols:
        con.execute("ALTER TABLE evals ADD COLUMN regime TEXT")
    if "bucket" not in cols:
        con.execute("ALTER TABLE evals ADD COLUMN bucket TEXT")


def _write_regime_evals(lineage_id: int, regime: str, pack: dict, receipt: str) -> None:
    try:
        import factor_lineage_v1_1 as FL
    except Exception as e:
        print(f"[ic_eval] lineage 不可用:{e}")
        return
    con = FL.connect()
    _ensure_regime_cols(con)
    con.commit()
    for lab, s in pack["buckets"].items():
        v = s["verdict"]
        stored = v if v in FL.VERDICTS else ("watch" if v.startswith("watch") or v == "regime_flip" else "reject")
        eid = FL.record_eval(
            lineage_id, s.get("first") or "", s.get("last") or "", f"{s.get('horizon')}d",
            s["n_obs"], s["ic_mean"], s["ic_std"], "close_to_close",
            None, receipt, stored, s.get("reason") or "",
        )
        con.execute("UPDATE evals SET regime=?, bucket=? WHERE id=?", (regime, lab, eid))
    con.commit()
    con.close()


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
