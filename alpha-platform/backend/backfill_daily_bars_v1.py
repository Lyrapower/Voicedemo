"""backfill_daily_bars v1 · 向前回填 daily_bars 历史(2026-09-02,砥)

现网只从 2026-06-29 起有 bars(49 交易日),IC 评估要 ≥ 66。本脚本用现网同一端点
  $FMP_BASE/historical-price-eod/full?symbol=S&from=YYYY-MM-DD&to=YYYY-MM-DD   (SPEC_8600 §2 现网路径)
逐票向前补到 --since,只插库里没有的 (ts, symbol);ts 按库里现有约定(取现有行的 秒-of-day 偏移复制)。
不换端点、不加新源、不动表结构。key 只从 FMP_API_KEY 读,不进任何输出。

  python3 backfill_daily_bars_v1.py --db <platform.db> --since 2025-09-01 --dry-run     # 只算计划:多少票、多少调用,零 HTTP
  python3 backfill_daily_bars_v1.py --db <platform.db> --since 2025-06-01 --symbols /data/sp500_symbols.json   # 只补 sp500,501 次 GET
  python3 backfill_daily_bars_v1.py --db <platform.db> --since 2025-09-01 --limit 20    # 冒烟 20 票
  python3 backfill_daily_bars_v1.py --db <platform.db> --since 2025-09-01               # 全量,可中断续跑(state 文件)
  python3 backfill_daily_bars_v1.py selftest

限速 --rpm(默认 240,低于 FMP 280/min);429/5xx 退避重试 3 次;每票一行进度到 stderr,不含 URL。
退出码:0 完成;2 参数/环境错;4 部分失败(state 里有 failed 列表,重跑只补失败的)。
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys, time
from datetime import datetime, timezone, timedelta

FMP_BASE = os.environ.get("FMP_BASE", "https://financialmodelingprep.com/stable").rstrip("/")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------- 库 ----------

def existing(con: sqlite3.Connection) -> tuple[dict[str, float], set[tuple[str, str]], float, bool]:
    """每票最早 ts、已有 (date,symbol) 集、ts 的秒-of-day 偏移、ts 是否文本。"""
    rows = con.execute("SELECT symbol, MIN(ts), typeof(ts) FROM daily_bars GROUP BY symbol").fetchall()
    first = {r[0]: r[1] for r in rows}
    is_text = bool(rows) and rows[0][2] == "text"
    have = set()
    for ts, sym in con.execute("SELECT ts, symbol FROM daily_bars"):
        have.add((_to_date(ts), sym))
    off = 0.0
    if rows and not is_text:
        ts0 = float(rows[0][1]); off = ts0 - (ts0 // 86400) * 86400
    return first, have, off, is_text


def _to_date(ts) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    return str(ts)[:10]


def _to_ts(date: str, off: float, is_text: bool):
    if is_text:
        return date
    d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return d.timestamp() + off


# ---------- 拉 ----------

def fetch_history(symbol: str, frm: str, to: str, key: str, timeout: float = 30.0) -> list[dict]:
    import urllib.request, urllib.parse, urllib.error
    q = urllib.parse.urlencode({"symbol": symbol, "from": frm, "to": to, "apikey": key})
    url = f"{FMP_BASE}/historical-price-eod/full?{q}"
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "grid-backfill/1"}), timeout=timeout) as r:
                data = json.loads(r.read().decode())
            if isinstance(data, dict):        # 有的形状包一层
                data = data.get("historical") or data.get("data") or []
            return data if isinstance(data, list) else []
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2.0 * (attempt + 1)); continue
            raise RuntimeError(last)
        except Exception as e:  # noqa
            last = type(e).__name__; time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {last}")


def rows_from(data: list[dict], symbol: str) -> list[tuple[str, float, float, float, float, float]]:
    out = []
    for d in data:
        try:
            date = str(d.get("date"))[:10]
            c = float(d.get("close") if d.get("close") is not None else d.get("adjClose"))
            if c <= 0: continue
            out.append((date, float(d.get("open") or c), float(d.get("high") or c), float(d.get("low") or c), c, float(d.get("volume") or 0)))
        except (TypeError, ValueError):
            continue
    return out


# ---------- 主流程 ----------

def load_symbols(spec: str | None) -> set[str] | None:
    """--symbols:JSON 文件({"symbols":[...]} 或 [...])或逗号分隔;None=库内全部。"""
    if not spec: return None
    if os.path.exists(spec):
        data = json.load(open(spec)); data = data.get("symbols", data) if isinstance(data, dict) else data
        return {str(x).strip().upper() for x in data if str(x).strip()}
    return {x.strip().upper() for x in spec.split(",") if x.strip()}


def run(db: str, since: str, key: str | None, dry: bool, limit: int | None, rpm: int, state_path: str, fetch=fetch_history, only: set[str] | None = None) -> int:
    con = sqlite3.connect(db)
    first, have, off, is_text = existing(con)
    state = json.load(open(state_path)) if os.path.exists(state_path) else {"done": [], "failed": {}, "inserted": 0}
    done = set(state["done"])
    todo = []
    for sym, ts0 in sorted(first.items()):
        if sym in done: continue
        if only is not None and sym.upper() not in only: continue
        d0 = _to_date(ts0)
        if d0 <= since: continue           # 已够早
        to = (datetime.strptime(d0, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        todo.append((sym, since, to))
    if limit: todo = todo[:limit]
    _log(f"plan: symbols={len(first)} todo={len(todo)} done={len(done)} since={since} ts_mode={'text' if is_text else f'unix(off={off:.0f}s)'} rpm={rpm}")
    if dry:
        _log(f"dry-run: 约 {len(todo)} 次 GET,~{len(todo)/rpm:.1f} 分钟;零 HTTP,退出"); return 0
    if not key:
        _log("FMP_API_KEY 未设"); return 2
    interval = 60.0 / rpm; t_last = 0.0; ins_total = 0
    for i, (sym, frm, to) in enumerate(todo, 1):
        wait = interval - (time.time() - t_last)
        if wait > 0: time.sleep(wait)
        t_last = time.time()
        try:
            data = fetch(sym, frm, to, key)
            rows = [(d, o, h, l, c, v) for (d, o, h, l, c, v) in rows_from(data, sym) if (d, sym) not in have and frm <= d <= to]
            con.executemany("INSERT INTO daily_bars(ts,symbol,o,h,l,c,v) VALUES(?,?,?,?,?,?,?)",
                            [(_to_ts(d, off, is_text), sym, o, h, l, c, v) for (d, o, h, l, c, v) in rows])
            con.commit(); ins_total += len(rows)
            for (d, *_r) in rows: have.add((d, sym))
            state["done"].append(sym); state["failed"].pop(sym, None)
            _log(f"[{i}/{len(todo)}] {sym} +{len(rows)}")
        except Exception as e:  # noqa
            state["failed"][sym] = str(e); _log(f"[{i}/{len(todo)}] {sym} FAIL {e}")
        if i % 25 == 0 or i == len(todo):
            state["inserted"] = state.get("inserted", 0) + ins_total; ins_total = 0
            json.dump(state, open(state_path, "w"))
    con.close()
    n_fail = len(state["failed"]); _log(f"done: inserted_total={state.get('inserted',0)} failed={n_fail} state={state_path}")
    return 4 if n_fail else 0


# ---------- 自测(stub 抓取,零 HTTP) ----------

def selftest() -> int:
    import tempfile, random
    t = tempfile.mkdtemp(); db = os.path.join(t, "p.db"); con = sqlite3.connect(db)
    con.execute("CREATE TABLE daily_bars(ts REAL, symbol TEXT, o REAL, h REAL, l REAL, c REAL, v REAL)")
    base = datetime(2026, 6, 29, 4, 0, tzinfo=timezone.utc)   # 库里约定:04:00 UTC(= ET 午夜)
    for sym in ("AAA", "BBB", "CCC"):
        for d in range(5):
            con.execute("INSERT INTO daily_bars VALUES(?,?,?,?,?,?,?)", ((base + timedelta(days=d)).timestamp(), sym, 1, 1, 1, 100 + d, 1))
    con.commit(); con.close()
    calls = []
    def stub(sym, frm, to, key):
        calls.append((sym, frm, to)); rng = random.Random(sym)
        d0 = datetime.strptime(frm, "%Y-%m-%d"); d1 = datetime.strptime(to, "%Y-%m-%d")
        out, d = [], d0
        while d <= d1:
            if d.weekday() < 5: out.append({"date": d.strftime("%Y-%m-%d"), "open": 90, "high": 91, "low": 89, "close": 90 + rng.random(), "volume": 1000})
            d += timedelta(days=1)
        out.append({"date": "2026-06-30", "close": 999})    # 已有日期,须被去重跳过
        if sym == "BBB": raise RuntimeError("HTTP 503")      # 一票失败,须进 failed,可续跑
        return out
    st = os.path.join(t, "state.json"); fails = []
    rc = run(db, "2026-06-01", "k", dry=True, limit=None, rpm=6000, state_path=st, fetch=stub); fails += [] if rc == 0 and not calls else ["dry-run 发了请求或非 0"]
    rc = run(db, "2026-06-01", "k", dry=False, limit=None, rpm=6000, state_path=st, fetch=stub)
    con = sqlite3.connect(db)
    n_aaa = con.execute("SELECT COUNT(*) FROM daily_bars WHERE symbol='AAA'").fetchone()[0]
    dup = con.execute("SELECT COUNT(*) FROM daily_bars WHERE symbol='AAA' AND c=999").fetchone()[0]
    off = con.execute("SELECT ts - (CAST(ts/86400 AS INT)*86400) FROM daily_bars WHERE symbol='AAA' ORDER BY ts LIMIT 1").fetchone()[0]
    fails += [] if rc == 4 else [f"一票失败应退 4,得 {rc}"]
    fails += [] if n_aaa == 5 + 20 else [f"AAA 应 25 行(5 原 + 20 个工作日),得 {n_aaa}"]
    fails += [] if dup == 0 else ["已有日期未去重"]
    fails += [] if abs(off - 4 * 3600) < 1 else [f"ts 偏移未沿用库约定 {off}"]
    s = json.load(open(st)); fails += [] if "BBB" in s["failed"] and "AAA" in s["done"] else ["state 未记 failed/done"]
    calls.clear()
    def stub2(sym, frm, to, key):
        calls.append((sym, frm, to))
        return [{"date": "2026-06-02", "close": 50}] if sym == "BBB" else stub(sym, frm, to, key)
    rc = run(db, "2026-06-01", "k", dry=False, limit=None, rpm=6000, state_path=st, fetch=stub2)
    fails += [] if rc == 0 and calls == [("BBB", "2026-06-01", "2026-06-28")] else [f"续跑应只补 BBB,得 {calls} rc={rc}"]
    calls.clear(); st2 = os.path.join(t, "state2.json")
    run(db, "2026-05-01", "k", dry=True, limit=None, rpm=6000, state_path=st2, fetch=stub2, only={"CCC"})
    fails += [] if load_symbols("aaa, bbb") == {"AAA", "BBB"} else ["symbols 逗号解析错"]
    import json as _j; sp = os.path.join(t, "sp.json"); _j.dump({"symbols": ["CCC"]}, open(sp, "w"))
    fails += [] if load_symbols(sp) == {"CCC"} else ["symbols JSON 解析错"]
    con.close()
    if fails:
        print("SELFTEST FAIL"); [print(" -", f) for f in fails]; return 1
    print("SELFTEST PASS 7/7(dry-run 零请求 / 去重 / ts 偏移沿用 / 失败进 state / 续跑只补失败 / 退出码 / --symbols 过滤)"); return 0


def main(argv):
    if len(argv) > 1 and argv[1] == "selftest": return selftest()
    ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); ap.add_argument("--since", required=True)
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--limit", type=int); ap.add_argument("--rpm", type=int, default=240)
    ap.add_argument("--state", default=None); ap.add_argument("--symbols", default=None, help="只补这些票:JSON 文件(sp500_symbols.json)或逗号分隔")
    a = ap.parse_args(argv[1:])
    state = a.state or os.path.join(os.path.dirname(os.path.abspath(a.db)), "backfill_daily_bars_state.json")
    return run(a.db, a.since, os.environ.get("FMP_API_KEY"), a.dry_run, a.limit, a.rpm, state, only=load_symbols(a.symbols))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
