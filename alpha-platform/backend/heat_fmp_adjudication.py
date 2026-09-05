#!/usr/bin/env python3
"""处决案：盘中 10 样本 · FMP vs Alpaca IEX（Lyra 2026-09-03 · 溯 复验窗）。

窗：10:00–15:00 ET。启动先印 ET 时刻与 SPY 的 FMP timestamp，差 = 真 lag。
用法:
  python3 heat_fmp_adjudication.py
  python3 heat_fmp_adjudication.py --samples 10 --interval 6
  python3 heat_fmp_adjudication.py --force   # 窗外（收盘后样本无效，仅调试）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

import db
import fmp_heat_quotes
import heat_nomination
from factor_truth import fetch_fmp_quote

ET = ZoneInfo("America/New_York")
WINDOW_START = dt.time(10, 0)
WINDOW_END = dt.time(15, 0)


def _now_et() -> dt.datetime:
    return dt.datetime.now(ET)


def _fmt_et(ts: int | None) -> str:
    if not ts:
        return "—"
    return dt.datetime.fromtimestamp(int(ts), tz=ET).strftime("%Y-%m-%d %H:%M:%S ET")


def _in_window(now: dt.datetime) -> bool:
    return WINDOW_START <= now.time() <= WINDOW_END and now.weekday() < 5


def _cell(v, fmt: str = "") -> str:
    if v is None:
        return "—"
    return format(v, fmt) if fmt else str(v)


def _print_table(rows: list[dict]) -> None:
    hdr = (
        f"{'sym':<6} {'lag_s':>7} {'|Δ|%':>8} {'fmp':>10} {'alpaca':>10} "
        f"{'bid':>8} {'ask':>8} {'stale':<6}"
    )
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        dlt = (row["delta_pct"] * 100) if row["delta_pct"] is not None else None
        print(
            f"{row['symbol']:<6} "
            f"{_cell(row['lag_s'], '7d')} "
            f"{_cell(dlt, '8.3f')} "
            f"{_cell(row['fmp_price'], '10.2f')} "
            f"{_cell(row['alpaca_last'], '10.2f')} "
            f"{_cell(row['alpaca_bid'], '8.2f')} "
            f"{_cell(row['alpaca_ask'], '8.2f')} "
            f"{'STALE' if row['stale'] else 'ok':<6}"
        )


def _one_sample(watchlist: list[str], sample_i: int) -> dict:
    t0 = int(time.time())
    quote_map, req_n, mode = fmp_heat_quotes.fetch_fmp_batch_quotes(watchlist)
    alpaca = fmp_heat_quotes._fetch_alpaca_iex(watchlist)
    rows = []
    stale_any = False
    for sym in watchlist:
        fq = quote_map.get(sym) or {}
        fmp_price = fq.get("price")
        fmp_ts = int(fq.get("quote_ts") or 0)
        aq = alpaca.get(sym) or {}
        alp_last = aq.get("last")
        lag_s = (t0 - fmp_ts) if fmp_ts else None
        delta_pct = None
        if fmp_price and alp_last:
            delta_pct = abs(float(alp_last) - float(fmp_price)) / float(fmp_price)
        stale = (
            not fmp_price
            or (lag_s is not None and lag_s > fmp_heat_quotes.CROSSCHECK_LAG_S)
            or (delta_pct is not None and delta_pct > fmp_heat_quotes.CROSSCHECK_DELTA_PCT)
        )
        if stale:
            stale_any = True
        rows.append({
            "symbol": sym,
            "fmp_price": fmp_price,
            "fmp_ts": fmp_ts,
            "lag_s": lag_s,
            "alpaca_last": alp_last,
            "alpaca_bid": aq.get("bid"),
            "alpaca_ask": aq.get("ask"),
            "delta_pct": round(delta_pct, 6) if delta_pct is not None else None,
            "stale": stale,
        })
    return {
        "sample": sample_i,
        "read_ts": t0,
        "mode": mode,
        "req_n": req_n,
        "stale_any": stale_any,
        "rows": rows,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--samples", type=int, default=10)
    p.add_argument("--interval", type=float, default=6.0)
    p.add_argument("--force", action="store_true", help="窗外仍跑（收盘后样本无效）")
    args = p.parse_args()
    if not os.getenv("FMP_API_KEY", "").strip():
        print("ERROR: FMP_API_KEY unset", file=sys.stderr)
        return 2

    now_et = _now_et()
    start_unix = int(now_et.timestamp())
    print(f"script_start_et={now_et.strftime('%Y-%m-%d %H:%M:%S ET')} unix={start_unix}")

    spy = fetch_fmp_quote("SPY")
    spy_ts = int(spy["quote_ts"]) if spy and spy.get("quote_ts") else None
    true_lag = (start_unix - spy_ts) if spy_ts else None
    print(
        f"SPY_fmp_timestamp={spy_ts} ({_fmt_et(spy_ts)}) "
        f"price={spy.get('price') if spy else None}"
    )
    print(f"true_lag_s={true_lag}  (script_start − SPY FMP timestamp)")

    in_win = _in_window(now_et)
    print(
        f"window=10:00–15:00 ET weekday · in_window={in_win} "
        f"{'(ok)' if in_win else '(收盘后/窗外样本无效)'}"
    )
    if not in_win and not args.force:
        print("ABORT: 不在 10:00–15:00 ET。盘中复验待该窗内重跑。用 --force 仅调试。")
        return 3

    c = db.conn()
    try:
        heat = heat_nomination.resolve_heat(refresh=False, conn=c)
        wl = list(heat.get("watchlist") or [])
    finally:
        c.close()
    if not wl:
        print("ERROR: empty watchlist", file=sys.stderr)
        return 2
    print(f"adjudication watchlist n={len(wl)} samples={args.samples} interval={args.interval}s")
    report: list[dict] = []
    for i in range(args.samples):
        s = _one_sample(wl, i + 1)
        report.append(s)
        print(f"\n=== sample {s['sample']} @ {_fmt_et(s['read_ts'])} mode={s.get('mode')} stale_any={s['stale_any']} ===")
        _print_table(s["rows"])
        if i + 1 < args.samples:
            time.sleep(max(0.5, args.interval))
    max_lag = max((r["lag_s"] or 0) for s in report for r in s["rows"])
    max_delta = max((r["delta_pct"] or 0) for s in report for r in s["rows"])
    stale_total = sum(1 for s in report for r in s["rows"] if r["stale"])
    summary = {
        "script_start_et": now_et.strftime("%Y-%m-%d %H:%M:%S ET"),
        "spy_fmp_ts": spy_ts,
        "true_lag_s": true_lag,
        "in_window": in_win,
        "watchlist_n": len(wl),
        "samples": args.samples,
        "max_lag_s": max_lag,
        "max_delta_pct": max_delta,
        "stale_cell_count": stale_total,
        "pass_lag_60": max_lag <= 60,
        "pass_delta_0p5": max_delta <= 0.005,
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    return 0 if summary["pass_lag_60"] and summary["pass_delta_0p5"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
