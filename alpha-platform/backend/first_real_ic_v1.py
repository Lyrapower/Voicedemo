"""first_real_ic v1.1 · 一条命令跑完第一批真 IC(2026-09-02,砥)

  python3 first_real_ic_v1.py --db <daily_bars 所在 sqlite> [--horizon 5] [--out aether_nexus/docs]

做什么(全自动,不问):
  1. 查 daily_bars 覆盖:截面不足(<20 symbol/日)→ 退出 3 不评估;只差天数 → 照评但判定一律 insufficient(只记不裁,回执标"初值"),退出 0。
  2. 登记四个内置起跑因子(mom_5 / mom_20 / rev_1 / vol_20)进 lineage(已存在则复用 id)。
  3. 逐个评估(ic_eval_v1_1.evaluate),写 evals(settlement=close_to_close),自动判定。
  4. 打印榜 / 死枝 / 预算,打印仪表 /api/state JSON。
  5. 写回执 FIRST_REAL_IC_<date>.md 到 --out(默认当前目录):覆盖、四因子表、榜、原样命令。
依赖:同目录的 factor_lineage_v1_1.py 与 ic_eval_v1_1.py;标准库。LINEAGE 库路径沿 FACTOR_LINEAGE_DB(默认 state/factor_lineage.db)。
"""
from __future__ import annotations
import argparse, json, logging, os, sqlite3, sys, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import factor_lineage_v1_1 as FL   # noqa: E402
import ic_eval_v1_1 as IE          # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("first_real_ic_v1")

PRICE_BASIS = "split-adjusted close (FMP historical-price-eod/full), not dividend-adjusted"

BUILTINS = [("mom_5", "close/close[-5]-1", "5 日动量:短期趋势延续"),
            ("mom_20", "close/close[-20]-1", "20 日动量:月度趋势延续"),
            ("rev_1", "-(close/close[-1]-1)", "隔日反转:短期过度反应回归"),
            ("vol_20", "-std(ret,20)", "低波动溢价:低波动标的风险调整后收益更高")]


def coverage(db: str, symbols: list[str] | None = None) -> dict:
    con = sqlite3.connect(db)
    try:
        where = ""
        args: list = []
        if symbols:
            where = " WHERE symbol IN (%s)" % ",".join("?" * len(symbols))
            args = symbols
        n, ns, mn, mx = con.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(ts), MAX(ts) FROM daily_bars" + where, args).fetchone()
        days = con.execute("SELECT COUNT(DISTINCT CASE WHEN typeof(ts)='text' THEN substr(ts,1,10) ELSE date(ts,'unixepoch') END) FROM daily_bars" + where, args).fetchone()[0]
        per_day = con.execute("SELECT AVG(c) FROM (SELECT COUNT(DISTINCT symbol) c FROM daily_bars" + where + " GROUP BY CASE WHEN typeof(ts)='text' THEN substr(ts,1,10) ELSE date(ts,'unixepoch') END)", args).fetchone()[0]
    finally:
        con.close()
    return {"rows": n, "symbols": ns, "days": days, "symbols_per_day_avg": round(per_day or 0, 1),
            "first": IE._to_date(mn) if mn is not None else None, "last": IE._to_date(mx) if mx is not None else None}


def _eval_count() -> int:
    try:
        con = sqlite3.connect(FL._db_path())
        try:
            return int(con.execute("SELECT COUNT(*) FROM evals").fetchone()[0])
        finally:
            con.close()
    except Exception:
        return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True); ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--out", default="."); ap.add_argument("--receipt", default=None)
    ap.add_argument("--universe", required=True, help="json 文件 {symbols:[...]} 或 [...];IC 只算这些 symbol")
    a = ap.parse_args(argv[1:])
    symbols = IE._load_universe(a.universe)
    day = datetime.now().strftime("%Y-%m-%d")
    receipt = a.receipt or f"first_real_ic_{day}"
    lines = [f"# 第一批真 IC · {day}", "",
             f"- price basis = {PRICE_BASIS}",
             f"- bars: `{a.db}` · lineage: `{FL._db_path()}` · horizon {a.horizon}d · settlement close_to_close · universe {a.universe}({len(symbols)} symbols)",
             f"- 命令:`python3 first_real_ic_v1.py --db {a.db} --horizon {a.horizon} --universe {a.universe}`", ""]

    cov = coverage(a.db, symbols)
    need_days = IE.MIN_N + a.horizon + 1
    lines += ["## 覆盖", f"- rows {cov['rows']} · symbols {cov['symbols']} · 交易日 {cov['days']} · 日均标的 {cov['symbols_per_day_avg']} · {cov['first']} → {cov['last']}",
              f"- 门槛:≥ {IE.MIN_NAMES} symbol/日 且 ≥ {need_days} 交易日(MIN_N {IE.MIN_N} + horizon {a.horizon} + 1)"]
    print(json.dumps({"coverage": cov, "need_days": need_days, "min_names": IE.MIN_NAMES}, ensure_ascii=False))
    short = []
    if cov["symbols_per_day_avg"] < IE.MIN_NAMES:
        short.append(f"日均标的 {cov['symbols_per_day_avg']} < {IE.MIN_NAMES}")
    if cov["days"] < need_days:
        short.append(f"交易日 {cov['days']} < {need_days},差 {need_days - cov['days']} 天")
    prelim = False
    if cov["symbols_per_day_avg"] < IE.MIN_NAMES:
        lines += ["", "## 结论", "截面不足,未评估:" + ";".join(short), "不补数据。"]
        _write(a.out, receipt, lines); print("INSUFFICIENT_DATA:", "; ".join(short)); return 3
    if short:   # 只差天数:照评,但判定一律 insufficient(只记不裁),回执标"初值"
        prelim = True
        lines += ["", "**初值:交易日不足,以下 IC 只记不裁(verdict=insufficient),不作晋级/否决依据;补足 %d 天后重跑。**" % (need_days - cov["days"])]
        print("PRELIMINARY:", "; ".join(short), "→ 照评,只记不裁")

    bars = IE.load_bars(a.db, symbols=symbols)
    evals_before = _eval_count()
    lines += ["", "## 四个起跑因子", "| 因子 | id | IC | std | t | 命中 | 天 | 日均标的 | 判定 | 理由 |", "|---|---|---|---|---|---|---|---|---|---|"]
    rows = []
    written = 0
    for name, expr, why in BUILTINS:
        try:
            fid = FL.propose(expr, name, "manual", None, "lyra", why, universe="sp500")
            FL.record_sandbox(fid, True, f"{receipt}:builtin", "")
            t0 = time.time()
            s = IE.evaluate(bars, IE.FACTORS[name], a.horizon)
            v, reason = IE.auto_verdict(s)
            if prelim:
                v, reason = "insufficient", f"初值 n={s['n_obs']}<{IE.MIN_N}:" + reason
            eid = IE.write_lineage(s, fid, receipt, v, reason)
        except sqlite3.OperationalError as exc:
            log.error("first_real_ic: lineage write failed (%s): %s", name, exc)
            eid = None
            s = {"ic_mean": None, "ic_std": None, "ic_t": None, "hit": None, "n_obs": 0}
            v, reason = "error", str(exc)
            fid = None
            t0 = time.time()
        if eid is not None:
            written += 1
        f = lambda x, d=4: "—" if x is None else f"{x:.{d}f}"
        rows.append((name, fid, s, v, reason, eid))
        line = f"| {name} | {fid} | {f(s['ic_mean'])} | {f(s['ic_std'])} | {f(s['ic_t'], 2)} | {f(s['hit'], 2)} | {s['n_obs']} | {f(s.get('names_avg'), 1)} | {v} | {reason} |"
        lines.append(line)
        print(f"{name:<8} id={fid} ic={f(s['ic_mean'])} std={f(s['ic_std'])} t={f(s['ic_t'],2)} hit={f(s['hit'],2)} n={s['n_obs']} names={f(s.get('names_avg'),1)} verdict={v} ({reason}) eval_id={eid} {time.time()-t0:.1f}s")

    lb = FL.leaderboard(); dead = FL.dead_branches(); bud = FL.budget()
    lines += ["", "## 榜(n ≥ %d,按 t)" % IE.MIN_N] + [f"- #{r['id']} {r['name']} ic={r['ic_mean']:.4f} t={r['ic_t']:.2f} n={r['n_obs']} {r['verdict']}" for r in lb]
    lines += ["", "## 死枝"] + ([f"- #{d['id']} {d['name']}: {d['reject_reason']}" for d in dead] or ["- 无"])
    lines += ["", f"## 预算 live {bud['live']} / {bud['max_live']} · 登记 {bud['total']}"]
    print("leaderboard:", [(r["name"], round(r["ic_t"], 2), r["verdict"]) for r in lb]); print("dead:", [(d["name"], d["reject_reason"]) for d in dead]); print("budget:", bud)

    try:
        import lineage_dashboard_v1_1 as LD
        st = LD.state(FL._db_path())
        js = json.dumps(st, ensure_ascii=False, default=str)
        print("dashboard /api/state:", js[:600] + ("…" if len(js) > 600 else ""))
        lines += ["", "## 仪表 /api/state(截前 600 字)", "```", js[:600], "```"]
    except Exception as e:  # noqa
        print("dashboard state 未取到:", e)

    lines += ["", "读法:随机游走里动量本就不该显著;这里的意义是口径——close_to_close、天数为 n、Theta 中价另表。显著才要怀疑数据。"]
    p = _write(a.out, receipt, lines); print("receipt:", p)
    if written == 0:
        log.error(
            "first_real_ic: wrote 0 eval rows lineage=%s evals_before=%s evals_after=%s",
            FL._db_path(), evals_before, _eval_count(),
        )
        return 1
    return 0


def _write(out: str, name: str, lines: list[str]) -> str:
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, f"{name.upper()}.md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n\n—— first_real_ic_v1,砥\n")
    return p


if __name__ == "__main__":
    sys.exit(main(sys.argv))
