"""热力快循环 · FMP batch-quote 主源 + Alpaca IEX 交叉核对（不写主表）。"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from typing import Any
from zoneinfo import ZoneInfo

import httpx

import db

log = logging.getLogger("fmp_heat")

ET = ZoneInfo("America/New_York")
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()
FMP_BASE = os.getenv("FMP_BASE", "https://financialmodelingprep.com/stable").rstrip("/")
ALPACA_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY", "")
CROSSCHECK_LAG_S = int(os.getenv("HEAT_CROSSCHECK_LAG_S", "60"))
CROSSCHECK_DELTA_PCT = float(os.getenv("HEAT_CROSSCHECK_DELTA_PCT", "0.005"))

HEAT_CROSSCHECK_DDL = """
CREATE TABLE IF NOT EXISTS heat_crosscheck(
  symbol TEXT PRIMARY KEY,
  fmp_price REAL, fmp_ts INTEGER,
  alpaca_last REAL, alpaca_bid REAL, alpaca_ask REAL,
  delta_pct REAL, lag_s REAL,
  stale INTEGER NOT NULL DEFAULT 0,
  checked_ts INTEGER NOT NULL,
  detail TEXT);
"""


def ensure_heat_schema(c) -> None:
    c.executescript(db.SCHEMA)
    try:
        c.execute("ALTER TABLE bars ADD COLUMN src TEXT")
    except Exception:
        pass
    c.executescript(HEAT_CROSSCHECK_DDL)


def _parse_quote_ts(raw: Any, *, fallback: int | None = None) -> int:
    if raw is None:
        return int(fallback or time.time())
    if isinstance(raw, (int, float)):
        ts = int(raw)
        return ts // 1000 if ts > 1_000_000_000_000 else ts
    s = str(raw).strip()
    if s.isdigit():
        ts = int(s)
        return ts // 1000 if ts > 1_000_000_000_000 else ts
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return int(dt.datetime.fromisoformat(s).timestamp())
    except Exception:
        return int(fallback or time.time())


def fetch_fmp_batch_quotes(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], int, str]:
    """拉全 watchlist。优先 batch-quote(1 req)；402 时 fallback 逐票 /stable/quote。

    返回 (quotes, http_req_count, mode)。
    """
    uniq = list(dict.fromkeys(s for s in symbols if s))
    if not uniq or not FMP_API_KEY:
        return {}, 0, "no_key"
    joined = ",".join(uniq)
    urls = (
        (f"{FMP_BASE}/batch-quote", {"symbols": joined, "apikey": FMP_API_KEY}),
        (
            "https://financialmodelingprep.com/api/v3/quote/" + joined,
            {"apikey": FMP_API_KEY},
        ),
    )
    last_err = ""
    for url, params in urls:
        try:
            r = httpx.get(url, params=params, timeout=20)
            if r.status_code == 402:
                last_err = "batch-quote 402 (tier restricted)"
                break
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("Error Message"):
                last_err = str(data["Error Message"])[:200]
                continue
            rows = data if isinstance(data, list) else data.get("quotes") or data.get("data") or []
            out: dict[str, dict[str, Any]] = {}
            now = int(time.time())
            for row in rows:
                sym = row.get("symbol") or row.get("ticker")
                price = row.get("price")
                if not sym or price in (None, 0):
                    continue
                qts = _parse_quote_ts(row.get("timestamp") or row.get("ts"), fallback=now)
                prev = row.get("previousClose") or row.get("previous_close")
                out[str(sym).upper()] = {
                    "price": float(price),
                    "volume": float(row.get("volume") or 0),
                    "quote_ts": qts,
                    "previousClose": float(prev) if prev not in (None, "", 0) else None,
                }
            if out:
                return out, 1, "batch-quote"
        except Exception as exc:
            last_err = str(exc)[:200]

    # 402 / batch 不可用：fallback 逐票 stable /quote（Scout 同档已验证）
    from factor_truth import fetch_fmp_quote

    out: dict[str, dict[str, Any]] = {}
    req_n = 0
    for sym in uniq:
        q = fetch_fmp_quote(sym)
        req_n += 1
        if q:
            out[sym] = {
                "price": q["price"],
                "volume": q.get("volume") or 0,
                "quote_ts": int(q["quote_ts"]),
                "previousClose": q.get("prev_close") or q.get("previousClose"),
            }
    mode = "stable/quote×N" if out else "fail"
    if not out and last_err:
        log.warning("fmp batch-quote failed: %s; fallback empty", last_err)
    elif last_err:
        log.warning("fmp batch-quote unavailable (%s); fallback %d×/stable/quote got %d", last_err, req_n, len(out))
    return out, req_n, mode


def store_fmp_quotes_to_bars(c, quotes: dict[str, dict[str, Any]]) -> int:
    """FMP quote → bars 主表，src=fmp_quote；previousClose → intraday_quotes。"""
    try:
        import factor_truth
        factor_truth.ensure_schema(c)
    except Exception:
        pass
    n = 0
    now = int(time.time())
    for sym, q in quotes.items():
        price = q["price"]
        ts = int(q["quote_ts"])
        vol = float(q.get("volume") or 0)
        c.execute(
            "INSERT OR REPLACE INTO bars(ts, symbol, o, h, l, c, v, src) VALUES(?,?,?,?,?,?,?,?)",
            (ts, sym, price, price, price, price, vol, "fmp_quote"),
        )
        prev = q.get("previousClose") or q.get("prev_close")
        if prev not in (None, "", 0):
            try:
                c.execute(
                    "INSERT OR REPLACE INTO intraday_quotes(symbol, price, prev_close, volume, quote_ts, fetched_ts) "
                    "VALUES(?,?,?,?,?,?)",
                    (sym, price, float(prev), vol, ts, now),
                )
            except Exception:
                pass
        n += 1
    return n


def _fetch_alpaca_iex(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Alpaca IEX last trade + snapshot bid/ask — 仅交叉核对，不写 bars。"""
    if not (ALPACA_KEY and ALPACA_SECRET) or not symbols:
        return {}
    headers = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}
    alpaca_syms = ",".join(dict.fromkeys(db.alpaca_ticker(s) for s in symbols))
    out: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=15) as cli:
        try:
            tr = cli.get(
                "https://data.alpaca.markets/v2/stocks/trades/latest",
                params={"symbols": alpaca_syms, "feed": "iex"},
                headers=headers,
            )
            tr.raise_for_status()
            for ak, row in (tr.json().get("trades") or {}).items():
                canon = db.canonical_ticker(ak, symbols)
                if not row:
                    continue
                out.setdefault(canon, {})["last"] = float(row.get("p") or 0) or None
                t = row.get("t")
                if t:
                    out[canon]["trade_ts"] = _parse_quote_ts(t)
        except Exception as exc:
            log.warning("alpaca trades/latest: %s", exc)
        try:
            sn = cli.get(
                "https://data.alpaca.markets/v2/stocks/snapshots",
                params={"symbols": alpaca_syms, "feed": "iex"},
                headers=headers,
            )
            sn.raise_for_status()
            for ak, row in (sn.json().get("snapshots") or {}).items():
                canon = db.canonical_ticker(ak, symbols)
                q = (row or {}).get("latestQuote") or {}
                out.setdefault(canon, {})
                if q.get("bp") is not None:
                    out[canon]["bid"] = float(q["bp"])
                if q.get("ap") is not None:
                    out[canon]["ask"] = float(q["ap"])
        except Exception as exc:
            log.warning("alpaca snapshots: %s", exc)
    return out


def crosscheck_alpaca_iex(
    c,
    symbols: list[str],
    fmp_quotes: dict[str, dict[str, Any]],
    *,
    now: int | None = None,
) -> dict[str, Any]:
    """对比 FMP vs Alpaca IEX；滞后 >60s 或 |Δ|>0.5% → stale=1，写 heat_crosscheck。"""
    ensure_heat_schema(c)
    now = int(now or time.time())
    alpaca = _fetch_alpaca_iex(symbols)
    stale_syms: list[str] = []
    rows_out: list[dict[str, Any]] = []
    for sym in symbols:
        fq = fmp_quotes.get(sym) or {}
        fmp_price = fq.get("price")
        fmp_ts = int(fq.get("quote_ts") or 0)
        aq = alpaca.get(sym) or {}
        alp_last = aq.get("last")
        bid = aq.get("bid")
        ask = aq.get("ask")
        lag_s = (now - fmp_ts) if fmp_ts else None
        delta_pct = None
        if fmp_price and alp_last:
            delta_pct = abs(float(alp_last) - float(fmp_price)) / float(fmp_price)
        stale = 0
        reasons: list[str] = []
        if not fmp_price or not fmp_ts:
            stale = 1
            reasons.append("fmp_missing")
        if lag_s is not None and lag_s > CROSSCHECK_LAG_S:
            stale = 1
            reasons.append(f"lag>{CROSSCHECK_LAG_S}s")
        if delta_pct is not None and delta_pct > CROSSCHECK_DELTA_PCT:
            stale = 1
            reasons.append(f"|Δ|>{CROSSCHECK_DELTA_PCT*100:.2f}%")
        if stale:
            stale_syms.append(sym)
            log.warning(
                "heat crosscheck STALE %s lag=%s delta=%.4f fmp=%s alpaca=%s",
                sym,
                lag_s,
                delta_pct or -1,
                fmp_price,
                alp_last,
            )
        detail = ",".join(reasons) if reasons else "ok"
        c.execute(
            "INSERT OR REPLACE INTO heat_crosscheck("
            "symbol, fmp_price, fmp_ts, alpaca_last, alpaca_bid, alpaca_ask, "
            "delta_pct, lag_s, stale, checked_ts, detail"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                sym,
                fmp_price,
                fmp_ts or None,
                alp_last,
                bid,
                ask,
                delta_pct,
                lag_s,
                stale,
                now,
                detail,
            ),
        )
        rows_out.append({
            "symbol": sym,
            "fmp_price": fmp_price,
            "fmp_ts": fmp_ts,
            "alpaca_last": alp_last,
            "alpaca_bid": bid,
            "alpaca_ask": ask,
            "delta_pct": delta_pct,
            "lag_s": lag_s,
            "stale": bool(stale),
            "detail": detail,
        })
    return {
        "checked_ts": now,
        "n": len(rows_out),
        "stale_n": len(stale_syms),
        "stale_symbols": stale_syms,
        "rows": rows_out,
    }


def pull_fmp_heat_quotes(c, watchlist: list[str]) -> dict[str, Any]:
    """热力主路径：FMP batch → bars(src=fmp_quote) → Alpaca 交叉核对。"""
    ensure_heat_schema(c)
    quotes, req_n, mode = fetch_fmp_batch_quotes(watchlist)
    n = store_fmp_quotes_to_bars(c, quotes) if quotes else 0
    cross = crosscheck_alpaca_iex(c, watchlist, quotes)
    status = "ok"
    if not quotes:
        status = "fail"
    elif cross["stale_n"] or mode != "batch-quote":
        status = "partial"
    detail = (
        f"fmp {mode} {n}/{len(watchlist)} · src=fmp_quote · "
        f"cross stale={cross['stale_n']} · req={req_n}"
    )
    db.set_health(c, "data_equity_heat", status, detail)
    db.set_health(
        c,
        "heat_crosscheck",
        status,
        json.dumps(
            {
                "stale_n": cross["stale_n"],
                "stale_symbols": cross["stale_symbols"][:8],
                "checked_ts": cross["checked_ts"],
            },
            ensure_ascii=False,
        )[:400],
    )
    return {"quotes": quotes, "stored": n, "crosscheck": cross, "mode": mode, "req_n": req_n}


# Lane B · 滑点参照（paper_exec_v1 落盘时用）
LANE_B_REF_FIELDS = {
    "ref_px": "FMP /stable/quote price at signal_ts (no bid/ask → no mid)",
    "ref_src": "fmp_quote",
    "compare_alpaca_bid": "Alpaca IEX snapshot bid — 对照列，非主价",
    "compare_alpaca_ask": "Alpaca IEX snapshot ask — 对照列，非主价",
    "slippage_vs_ref": "fill_px − ref_px",
}
