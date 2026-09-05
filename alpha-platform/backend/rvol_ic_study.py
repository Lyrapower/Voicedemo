#!/usr/bin/env python3
"""Lane I · offline RVOL IC. Alpaca IEX 1Min proxy. Writes /data/intraday_study.db only.

t(rvol) 只判「门 vs 排序键」。升排序键前须再用付费 1min 核一次。

docker exec alpha-platform-worker-1 python3 rvol_ic_study.py --probe
docker exec alpha-platform-worker-1 python3 rvol_ic_study.py --subset
docker exec alpha-platform-worker-1 python3 rvol_ic_study.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
from zoneinfo import ZoneInfo

import httpx
from alpaca_bars import bars_params

ET = ZoneInfo("America/New_York")
ALPACA_BARS = "https://data.alpaca.markets/v2/stocks/bars"
RPM_CAP = int(os.getenv("RVOL_IC_RPM", "180"))


def _study_db() -> str:
    return os.getenv("INTRADAY_STUDY_DB", "/data/intraday_study.db")
_CALL_TS: list[float] = []
VENUE = "iex"

SCHEMA = """
CREATE TABLE IF NOT EXISTS m1(
  symbol TEXT NOT NULL, ts INTEGER NOT NULL,
  o REAL, h REAL, l REAL, c REAL, v REAL,
  venue TEXT,
  UNIQUE(symbol, ts)
);
"""


def _pace() -> None:
    while True:
        now = time.time()
        while _CALL_TS and now - _CALL_TS[0] > 60:
            _CALL_TS.pop(0)
        if len(_CALL_TS) < RPM_CAP:
            _CALL_TS.append(now)
            return
        time.sleep(min(2.0, max(0.05, 60.0 - (now - _CALL_TS[0]) + 0.02)))


def _alpaca_headers() -> dict[str, str]:
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise SystemExit("ALPACA_API_KEY/ALPACA_SECRET_KEY missing")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _alpaca_bars(symbol: str, start: dt.date, end: dt.date, *, page_token: str | None = None) -> httpx.Response:
    _pace()
    start_s = dt.datetime.combine(start, dt.time(9, 25), tzinfo=ET).isoformat()
    end_s = dt.datetime.combine(end, dt.time(16, 5), tzinfo=ET).isoformat()
    params = bars_params(
        symbols=symbol,
        timeframe="1Min",
        limit=10000,
        feed="iex",
        start=start_s,
        end=end_s,
        page_token=page_token,
    )
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            return httpx.get(ALPACA_BARS, params=params, headers=_alpaca_headers(), timeout=120)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def probe_spy(days: int = 2) -> dict:
    today = dt.datetime.now(ET).date()
    start = today - dt.timedelta(days=days + 3)
    r = _alpaca_bars("SPY", start, today)
    out = {
        "http": r.status_code,
        "venue": VENUE,
        "n": None,
        "first_ts": None,
        "last_ts": None,
        "keys": None,
        "body_head": (r.text or "")[:240],
    }
    if r.status_code >= 400:
        return out
    body = r.json()
    bars = (body.get("bars") or {}).get("SPY") or []
    out["n"] = len(bars) if isinstance(bars, list) else 0
    if bars:
        out["keys"] = sorted(bars[0].keys()) if isinstance(bars[0], dict) else []
        out["first_ts"] = str((bars[-1] or {}).get("t"))
        out["last_ts"] = str((bars[0] or {}).get("t"))
    return out


def _conn() -> sqlite3.Connection:
    path = _study_db()
    if os.path.abspath(path) == "/data/platform.db" or os.path.basename(path) == "platform.db":
        raise SystemExit("Lane I must not write platform.db")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(m1)").fetchall()}
    if "venue" not in cols:
        c.execute("ALTER TABLE m1 ADD COLUMN venue TEXT")
        c.commit()
    return c


def _parse_row(row: dict) -> tuple | None:
    raw = row.get("date") or row.get("timestamp")
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = int(raw)
            ts = ts // 1000 if ts > 1_000_000_000_000 else ts
        else:
            s = str(raw).replace("Z", "+00:00")
            ts = int(dt.datetime.fromisoformat(s).timestamp())
    except Exception:
        return None
    try:
        return (
            ts,
            float(row.get("open") or row.get("o")),
            float(row.get("high") or row.get("h")),
            float(row.get("low") or row.get("l")),
            float(row.get("close") or row.get("c")),
            float(row.get("volume") or row.get("v") or 0),
        )
    except (TypeError, ValueError):
        return None


def _parse_alpaca(row: dict) -> tuple | None:
    raw = row.get("t") or row.get("timestamp")
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = int(raw)
            ts = ts // 1000 if ts > 1_000_000_000_000 else ts
        else:
            s = str(raw).replace("Z", "+00:00")
            ts = int(dt.datetime.fromisoformat(s).timestamp())
    except Exception:
        return None
    try:
        return (
            ts,
            float(row.get("o") if row.get("o") is not None else row.get("open")),
            float(row.get("h") if row.get("h") is not None else row.get("high")),
            float(row.get("l") if row.get("l") is not None else row.get("low")),
            float(row.get("c") if row.get("c") is not None else row.get("close")),
            float(row.get("v") if row.get("v") is not None else row.get("volume") or 0),
        )
    except (TypeError, ValueError):
        return None


def _alpaca_sym(symbol: str) -> str:
    return symbol.replace("-", ".")


def pull_symbol(c: sqlite3.Connection, symbol: str, start: dt.date, end: dt.date) -> int:
    token = None
    n = 0
    ask = _alpaca_sym(symbol)
    while True:
        r = _alpaca_bars(ask, start, end, page_token=token)
        if r.status_code in (400, 404, 422):
            print(f"[skip] {symbol}->{ask} http={r.status_code}")
            return n
        if r.status_code >= 400:
            raise SystemExit(f"Alpaca IEX {r.status_code} {symbol}")
        body = r.json()
        bars_map = body.get("bars") or {}
        bars = bars_map.get(ask) or bars_map.get(symbol) or bars_map.get(symbol.upper()) or []
        if isinstance(bars_map, list):
            bars = bars_map
        for row in bars or []:
            if not isinstance(row, dict):
                continue
            parsed = _parse_alpaca(row)
            if not parsed:
                continue
            ts, o, h, l, cl, v = parsed
            c.execute(
                "INSERT OR IGNORE INTO m1(symbol, ts, o, h, l, c, v, venue) VALUES(?,?,?,?,?,?,?,?)",
                (symbol, ts, o, h, l, cl, v, VENUE),
            )
            n += 1
        token = body.get("next_page_token")
        if not token:
            break
    return n


def _in_window(ts: int) -> bool:
    t = dt.datetime.fromtimestamp(ts, tz=ET)
    hm = t.hour * 60 + t.minute
    return 9 * 60 + 35 <= hm <= 15 * 60 + 55


def spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    rx = _ranks(xs)
    ry = _ranks(ys)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - 6 * d2 / (n * (n * n - 1))


def _ranks(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def compute_ic(c: sqlite3.Connection, *, lookback_wrong: bool = False) -> dict:
    import heat_rvol

    rows = c.execute("SELECT symbol, ts, c, v FROM m1 ORDER BY symbol, ts").fetchall()
    if not rows:
        print("no rows", file=sys.stderr)
        return {"ok": False, "error": "no rows"}
    by_sym: dict[str, list[tuple[int, float, float]]] = {}
    for sym, ts, cl, v in rows:
        by_sym.setdefault(sym, []).append((int(ts), float(cl), float(v or 0)))
    # per t: lists of (rvol, ret5m, fwd15)
    buckets: dict[int, list[tuple[float, float, float]]] = {}
    for _sym, seq in by_sym.items():
        for i in range(20, len(seq) - 15):
            ts, cl, _v = seq[i]
            if not _in_window(ts):
                continue
            vols = [p[2] for p in seq[i - 20 : i + 1]]
            rvol, _gate, _neg = heat_rvol.rvol_from_cumulative(vols)
            if i < 5:
                continue
            c0 = seq[i - 5][1]
            ret5 = (cl / c0 - 1) if c0 else None
            if lookback_wrong:
                c15 = seq[i - 15][1] if i >= 15 else None
            else:
                c15 = seq[i + 15][1]
            fwd = (c15 / cl - 1) if c15 and cl else None
            if rvol is None or ret5 is None or fwd is None:
                continue
            buckets.setdefault(ts, []).append((rvol, ret5, fwd))
    ics_r, ics_5, ics_cond = [], [], []
    half: dict[str, list[float]] = {}
    for ts, pts in buckets.items():
        if len(pts) < 3:
            continue
        rvols = [p[0] for p in pts]
        r5 = [p[1] for p in pts]
        fwd = [p[2] for p in pts]
        icr = spearman(rvols, fwd)
        ic5 = spearman(r5, fwd)
        cond = [(a, b, f) for a, b, f in pts if a >= 1.5]
        icc = spearman([p[1] for p in cond], [p[2] for p in cond]) if len(cond) >= 3 else None
        t = dt.datetime.fromtimestamp(ts, tz=ET)
        bucket = f"{t.hour:02d}:{0 if t.minute < 30 else 30:02d}"
        if icr is not None:
            ics_r.append(icr)
            half.setdefault(bucket, []).append(icr)
        if ic5 is not None:
            ics_5.append(ic5)
        if icc is not None:
            ics_cond.append(icc)

    def _summ(xs: list[float]) -> dict:
        if not xs:
            return {"mean": None, "std": None, "t": None, "n": 0}
        n = len(xs)
        mean = sum(xs) / n
        var = sum((x - mean) ** 2 for x in xs) / max(1, n - 1)
        std = var ** 0.5
        tstat = mean / (std / (n ** 0.5)) if std else None
        return {"mean": mean, "std": std, "t": tstat, "n": n}

    half_rows = {k: _summ(v) for k, v in sorted(half.items())}
    return {
        "ok": True,
        "venue": VENUE,
        "use": "t 只判门 vs 排序键;升排序键前须付费 1min 复核",
        "n_cross": len(ics_r),
        "rvol": _summ(ics_r),
        "ret5m": _summ(ics_5),
        "ret5m_rvol_ge_1p5": _summ(ics_cond),
        "half_hour": half_rows,
    }


def _sp500() -> list[str]:
    for path in (
        os.getenv("SP500_CACHE", ""),
        "/data/sp500_symbols.json",
        "/data/sp500.json",
    ):
        if not path:
            continue
        try:
            doc = json.load(open(path, encoding="utf-8"))
            if isinstance(doc, list):
                return [str(s).upper() for s in doc]
            return [str(s).upper() for s in (doc.get("symbols") or [])]
        except Exception:
            continue
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--subset", action="store_true")
    ap.add_argument("--lookback-wrong", action="store_true")
    args = ap.parse_args()
    if args.probe:
        print(json.dumps(probe_spy(), ensure_ascii=False, indent=2))
        return 0
    probe = probe_spy()
    print("[probe]", json.dumps({k: probe[k] for k in ("http", "venue", "n", "first_ts", "last_ts", "keys")}, ensure_ascii=False))
    if (probe.get("http") or 0) >= 400:
        print("Lane I stop: Alpaca IEX probe fail")
        return 2
    today = dt.datetime.now(ET).date()
    if args.subset:
        syms = ["SPY", "QQQ", "IWM"]
        start = today - dt.timedelta(days=4)
    else:
        syms = _sp500()[:501] or ["SPY"]
        start = today - dt.timedelta(days=60)
    c = _conn()
    try:
        pulled = 0
        for i, sym in enumerate(syms):
            n = pull_symbol(c, sym, start, today)
            pulled += n
            if (i + 1) % 25 == 0:
                c.commit()
                print(f"[pull] {i+1}/{len(syms)} rows={pulled} venue={VENUE}")
        c.commit()
        ic = compute_ic(c, lookback_wrong=args.lookback_wrong)
        print(json.dumps(ic, ensure_ascii=False, indent=2, default=str))
        return 0 if ic.get("ok") else 2
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
