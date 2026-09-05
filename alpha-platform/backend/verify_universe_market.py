#!/usr/bin/env python3
"""verify_universe_market.py · V1–V8 gate (SPEC_8600_UNIVERSE_MARKET_v1 §4).

Exit 0 = all pass; exit 1 = any FAIL (prints verdict lines).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UNIVERSE_PATH = os.getenv("UNIVERSE_MARKET_CACHE", "/data/universe_market.json")
SP500_PATH = os.getenv("SP500_SYMBOLS_CACHE", "/data/sp500_symbols.json")
PLATFORM_DB = os.getenv("PLATFORM_DB", "/data/platform.db")
ETF_DENY = frozenset({"IBIT", "BITO", "TSLL", "SOXL", "SPY", "QQQ"})
SURFACE_DENY = frozenset(
    s.strip().upper() for s in os.getenv("SURFACE_DENY", "TSLA,GOOGL,AEHR").split(",") if s.strip()
)
TRIPLE = ("MARA", "BMNR", "ASST")


def _load_json(path: str) -> dict | list | None:
    if not os.path.isfile(path):
        return None
    try:
        return json.loads(open(path, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError):
        return None


def v1_fresh_simulation() -> tuple[bool, str]:
    """V1: 03:00 ET sp500_daily=0 when bars ≥ last closed; RTH path documented."""
    os.environ.setdefault("PLATFORM_DB_DIRECT_WRITE", "1")
    import factor_truth

    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    c = sqlite3.connect(tmp.name)
    factor_truth.ensure_schema(c)
    monday = dt.date(2026, 8, 24)
    ts = int(dt.datetime.combine(monday, dt.time(0, 0), tzinfo=ET).timestamp())
    for sym in ("AAPL", "MSFT", "NVDA"):
        c.execute(
            "INSERT INTO daily_bars(ts,symbol,o,h,l,c,v) VALUES(?,?,?,?,?,?,?)",
            (ts, sym, 1, 1, 1, 100, 1e6),
        )
    c.commit()
    t0300 = dt.datetime(2026, 8, 25, 3, 0, tzinfo=ET)
    sp500 = ["AAPL", "MSFT", "NVDA"]

    def fresh(sym: str) -> bool:
        return factor_truth.has_fresh_daily_bar(c, sym, now=t0300)

    skipped = sum(1 for s in sp500 if fresh(s))
    n = factor_truth.pull_daily_bars(c, sp500, limit=2, skip_fresh=True)

    t1030 = dt.datetime(2026, 8, 25, 10, 30, tzinfo=ET)
    need_pull = [s for s in sp500 if not factor_truth.has_fresh_daily_bar(c, s, now=t1030)]
    ok = n == 0 and skipped == len(sp500) and len(need_pull) == len(sp500)
    msg = (
        f"V1 fresh: 03:00 ET sp500_daily={n} (expect 0) · skip_fresh={skipped}/{len(sp500)} · "
        f"10:30 would_pull={len(need_pull)}/{len(sp500)}"
    )
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
    return ok, msg


def v2_universe_file() -> tuple[bool, str]:
    doc = _load_json(UNIVERSE_PATH)
    if not isinstance(doc, dict):
        return False, f"V2 universe file missing or invalid: {UNIVERSE_PATH}"
    if doc.get("kind") != "universe_market":
        return False, f"V2 kind={doc.get('kind')} (expect universe_market)"
    n = int(doc.get("n") or 0)
    if n < 500:
        return False, f"V2 n={n} < 500"
    rows = doc.get("rows") or []
    defn = doc.get("definition") or {}
    px_min = float(defn.get("price_min") or 10)
    dv_min = float(defn.get("dollar_vol_min") or 5e7)
    mc_min = float(defn.get("mcap_min") or 3e8)
    ex_ok = {"NYSE", "NASDAQ", "AMEX"}
    bad = 0
    for r in rows:
        if float(r.get("price") or 0) < px_min:
            bad += 1
        elif float(r.get("dollar_vol") or 0) < dv_min:
            bad += 1
        elif float(r.get("market_cap") or 0) < mc_min:
            bad += 1
        elif str(r.get("exchange") or "").upper() not in ex_ok:
            bad += 1
    if bad:
        return False, f"V2 rows fail floors: {bad}/{len(rows)}"
    sp = _load_json(SP500_PATH)
    sp_syms = set(sp.get("symbols") or []) if isinstance(sp, dict) else set()
    u_syms = set(doc.get("symbols") or [])
    inter = len(sp_syms & u_syms)
    if inter <= 200:
        return False, f"V2 sp500∩universe={inter} (expect >200)"
    return True, f"V2 ok n={n} sp500∩={inter} asof_et={doc.get('asof_et')}"


def v3_etf_deny() -> tuple[bool, str]:
    doc = _load_json(UNIVERSE_PATH)
    if not isinstance(doc, dict):
        return False, "V3 skip — no universe file"
    syms = set(doc.get("symbols") or [])
    hit = sorted(syms & ETF_DENY)
    if hit:
        return False, f"V3 ETF处决 FAIL: {hit}"
    return True, "V3 ETF处决 ok — none of IBIT/BITO/TSLL/SOXL/SPY/QQQ in universe"


def v4_triple() -> tuple[bool, str]:
    doc = _load_json(UNIVERSE_PATH)
    if not isinstance(doc, dict):
        return False, "V4 skip — no universe file"
    rows = {str(r.get("symbol") or "").upper(): r for r in (doc.get("rows") or [])}
    defn = doc.get("definition") or {}
    px_min = float(defn.get("price_min") or 10)
    dv_min = float(defn.get("dollar_vol_min") or 5e7)
    mc_min = float(defn.get("mcap_min") or 3e8)
    lines: list[str] = []
    ok = True
    for sym in TRIPLE:
        r = rows.get(sym)
        if not r:
            lines.append(f"{sym}=OUT(missing row)")
            continue
        px, dv, mc = float(r["price"]), float(r["dollar_vol"]), float(r["market_cap"])
        fails = []
        if px < px_min:
            fails.append("price")
        if dv < dv_min:
            fails.append("dollar_vol")
        if mc < mc_min:
            fails.append("mcap")
        if fails:
            lines.append(f"{sym}=OUT({','.join(fails)}) px={px} dv={dv:.0f} mc={mc:.0f}")
        else:
            lines.append(f"{sym}=IN px={px} dv={dv:.0f} mc={mc:.0f}")
    return ok, "V4 triple: " + " · ".join(lines)


def v5_daily_bars() -> tuple[bool, str]:
    doc = _load_json(UNIVERSE_PATH)
    if not isinstance(doc, dict):
        return False, "V5 skip — no universe file"
    if not os.path.isfile(PLATFORM_DB):
        return False, f"V5 platform.db missing: {PLATFORM_DB}"
    import factor_truth

    c = sqlite3.connect(PLATFORM_DB)
    rows = sorted(doc.get("rows") or [], key=lambda x: -float(x.get("dollar_vol") or 0))[:200]
    have = 0
    stale: list[str] = []
    last_closed = factor_truth._last_closed_trading_day()
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        cnt = c.execute("SELECT COUNT(*) FROM daily_bars WHERE symbol=?", (sym,)).fetchone()[0]
        if cnt > 0:
            have += 1
        latest = factor_truth._latest_bar_date(c, sym)
        if latest and latest < last_closed - dt.timedelta(days=4):
            stale.append(sym)
    c.close()
    pct = 100.0 * have / max(len(rows), 1)
    ok = pct >= 90.0 and not stale
    msg = f"V5 top200 bar cover={have}/{len(rows)} ({pct:.1f}%) stale={stale[:5]}"
    return ok, msg


def v6_movers_floors() -> tuple[bool, str]:
    if not os.path.isfile(PLATFORM_DB):
        return False, f"V6 platform.db missing: {PLATFORM_DB}"
    os.environ.setdefault("PLATFORM_DB_DIRECT_WRITE", "1")
    import db
    import factor_truth

    c = db.conn()
    try:
        sp500 = factor_truth.load_sp500_symbols()
        bfs = set()
        payload = factor_truth._movers_from_daily_bars(c, sp500, bfs)
    finally:
        c.close()
    bad: list[str] = []
    for side in ("gainers", "losers"):
        for row in payload.get(side) or []:
            sym = row.get("sym") or row.get("symbol")
            if float(row.get("last") or 0) < factor_truth.MOVERS_PRICE_MIN:
                bad.append(f"{sym}:price")
            adv = row.get("adv20")
            if adv is not None and float(adv) < factor_truth.MOVERS_ADV20_MIN:
                bad.append(f"{sym}:adv20")
            if not row.get("universe"):
                bad.append(f"{sym}:no_universe_tag")
    if bad:
        return False, f"V6 movers floor FAIL: {bad[:8]}"
    return True, f"V6 movers ok with_data={payload.get('with_data')} gainers={len(payload.get('gainers') or [])}"


def v7_redline() -> tuple[bool, str]:
    os.environ.setdefault("PLATFORM_DB_DIRECT_WRITE", "1")
    import db
    import heat_nomination

    c = db.conn()
    try:
        heat = heat_nomination.resolve_heat(refresh=False, conn=c)
    finally:
        c.close()
    wl = set(heat.get("watchlist") or [])
    hit = sorted(wl & SURFACE_DENY)
    if hit:
        return False, f"V7 SURFACE_DENY in heat: {hit}"
    return True, f"V7 redline ok watchlist_n={len(wl)}"


def v8_fmp_quota() -> tuple[bool, str]:
    if not os.path.isfile(PLATFORM_DB):
        return False, f"V8 platform.db missing: {PLATFORM_DB}"
    doc = _load_json(UNIVERSE_PATH)
    u_n = int(doc.get("n") or 0) if isinstance(doc, dict) else 0
    sp = _load_json(SP500_PATH)
    sp_n = len(sp.get("symbols") or []) if isinstance(sp, dict) else 501
    cap = (sp_n + u_n) * 2 + 30
    c = sqlite3.connect(PLATFORM_DB)
    row = c.execute("SELECT value FROM platform_state WHERE key='fmp_daily_gets'").fetchone()
    c.close()
    count = 0
    if row:
        try:
            count = int(json.loads(row[0]).get("count") or 0)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    import factor_truth

    live = factor_truth.fmp_get_count_today()
    count = max(count, live)
    ok = count <= cap
    return ok, f"V8 fmp_gets={count} cap={cap} (sp500={sp_n}+univ={u_n})*2+30"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list e.g. V1,V2")
    args = ap.parse_args()
    only = {x.strip().upper() for x in (args.only or "").split(",") if x.strip()}
    checks = [
        ("V1", v1_fresh_simulation),
        ("V2", v2_universe_file),
        ("V3", v3_etf_deny),
        ("V4", v4_triple),
        ("V5", v5_daily_bars),
        ("V6", v6_movers_floors),
        ("V7", v7_redline),
        ("V8", v8_fmp_quota),
    ]
    fails = 0
    for name, fn in checks:
        if only and name not in only:
            continue
        try:
            ok, msg = fn()
        except Exception as exc:
            ok, msg = False, f"{name} EXCEPTION: {exc}"
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {msg}")
        if not ok:
            fails += 1
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
