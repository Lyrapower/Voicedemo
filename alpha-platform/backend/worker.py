"""Alpha Platform · Phase 0 · worker.py — 数据→因子→决策 循环。"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import statistics
import threading
import time
from zoneinfo import ZoneInfo

import httpx

import db
import scan_quarantine
import bfs_surface
from alpaca_bars import bars_params

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
# FMP key 不进 INFO 日志(httpx INFO 会把含 apikey= 的 URL 整行打出;2026-09-02 砥 P0)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("worker")

ET = ZoneInfo("America/New_York")
HEAT_TICK_SECONDS = max(30, int(os.getenv("HEAT_TICK_SECONDS", "60")))
SCAN_TICK_SECONDS = max(60, int(os.getenv("SCAN_TICK_SECONDS", os.getenv("TICK_SECONDS", "300"))))
TICK_SECONDS = SCAN_TICK_SECONDS  # legacy alias
CRYPTO_PRODUCTS = [s.strip() for s in os.getenv("CRYPTO_PRODUCTS", "BTC-USD,ETH-USD,SOL-USD").split(",") if s.strip()]
ALPACA_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY", "")
STOP_PCT = float(os.getenv("DECISION_STOP_PCT", "0.30"))
TARGET_PCT = float(os.getenv("DECISION_TARGET_PCT", "0.60"))

# Components whose health reflects data/factor/store sub-stages. If any report a
# non-ok status at the end of a cycle, the worker is marked "partial" instead of
# "ok" so the console surfaces degradation instead of a green tick over stale data.
_DEGRADED_COMPONENTS = ("data_crypto", "data_equity", "factor", "grid_store", "decisions_audit", "platform_db")
_OK_STATUSES = ("ok",)

_stop = threading.Event()
_alpaca_req_lock = threading.Lock()
_alpaca_req_minute: int = 0
_alpaca_req_count: int = 0
_heat_locked_n: int = 0


def _note_heat_locked(where: str, exc: BaseException) -> bool:
    """Return True if this is sqlite locked. Count for 30min 处决案."""
    global _heat_locked_n
    if "database is locked" not in str(exc).lower():
        return False
    _heat_locked_n += 1
    log.warning("heat_locked n=%d @ %s: %s", _heat_locked_n, where, exc)
    return True


def _record_alpaca_request(n: int = 1) -> int:
    """Count Alpaca HTTP requests per calendar minute (处决案 ≤5/min)."""
    global _alpaca_req_minute, _alpaca_req_count
    minute = int(time.time()) // 60
    with _alpaca_req_lock:
        if minute != _alpaca_req_minute:
            _alpaca_req_minute = minute
            _alpaca_req_count = 0
        _alpaca_req_count += n
        total = _alpaca_req_count
    if total > 5:
        log.warning("alpaca requests this minute: %s (>5 budget)", total)
    return total


def _collect_degraded_components(c) -> list[str]:
    """Return list of component names whose latest health status is not ok."""
    try:
        rows = c.execute(
            "SELECT component, status FROM health WHERE component IN (%s) "
            "ORDER BY ts DESC" % ",".join("?" * len(_DEGRADED_COMPONENTS)),
            _DEGRADED_COMPONENTS,
        ).fetchall()
    except Exception:
        return []
    seen: set[str] = set()
    degraded: list[str] = []
    for comp, status in rows:
        if comp in seen:
            continue
        seen.add(comp)
        if str(status).lower() not in _OK_STATUSES:
            degraded.append(f"{comp}={status}")
    return degraded


def _store_bars(c, canonical: str, bars: list) -> int:
    n = 0
    for b in bars:
        ts = int(dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp())
        c.execute(
            "INSERT OR REPLACE INTO bars(ts, symbol, o, h, l, c, v) VALUES(?,?,?,?,?,?,?)",
            (ts, canonical, b["o"], b["h"], b["l"], b["c"], b["v"]),
        )
        n += 1
    return n


def pull_crypto(c) -> None:
    ok = 0
    now = int(time.time())
    with httpx.Client(timeout=8) as cli:
        for prod in CRYPTO_PRODUCTS:
            try:
                r = cli.get(f"https://api.exchange.coinbase.com/products/{prod}/ticker")
                r.raise_for_status()
                d = r.json()
                price = float(d["price"])
                extra = {"bid": d.get("bid"), "ask": d.get("ask"), "volume": d.get("volume")}
                try:
                    st = cli.get(f"https://api.exchange.coinbase.com/products/{prod}/stats")
                    st.raise_for_status()
                    open_24h = float(st.json().get("open") or 0)
                    if open_24h:
                        extra["open_24h"] = open_24h
                        c.execute(
                            "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
                            (now, prod, "ret_1d", (price - open_24h) / open_24h),
                        )
                except Exception as exc:
                    log.warning("crypto stats %s: %s", prod, exc)
                c.execute(
                    "INSERT INTO ticks(ts, market, symbol, price, extra) VALUES(?,?,?,?,?)",
                    (now, "crypto", prod, price, json.dumps(extra)),
                )
                ok += 1
            except Exception as exc:
                log.warning("crypto %s: %s", prod, exc)
    db.set_health(c, "data_crypto", "ok" if ok else "fail", f"{ok}/{len(CRYPTO_PRODUCTS)} products")


def pull_equities(
    c,
    watchlist: list[str],
    *,
    health_component: str = "data_equity",
    batch_only: bool = False,
) -> None:
    """Alpaca IEX 1Min — 交叉核对/退路;主数将来 Theta NBBO + FMP quote(见 PORT_PROCESS_CONVENTION)。"""
    if not (ALPACA_KEY and ALPACA_SECRET):
        db.set_health(c, health_component, "skipped", "ALPACA_* 未配置")
        return
    if not watchlist:
        db.set_health(c, health_component, "skipped", "empty watchlist")
        return
    headers = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}
    got: set[str] = set()
    n = 0
    req_n = 0
    chunk_size = max(4, int(os.getenv("ALPACA_BARS_BATCH_CHUNK", "8")))
    max_req = max(1, int(os.getenv("ALPACA_HEAT_MAX_REQ", "5"))) if batch_only else 999
    try:
        with httpx.Client(timeout=12) as cli:
            chunks = (
                [watchlist[i : i + chunk_size] for i in range(0, len(watchlist), chunk_size)]
                if batch_only
                else [watchlist]
            )
            for chunk in chunks:
                alpaca_syms = list(dict.fromkeys(db.alpaca_ticker(s) for s in chunk))
                r = cli.get(
                    "https://data.alpaca.markets/v2/stocks/bars",
                    params=bars_params(
                        symbols=",".join(alpaca_syms),
                        timeframe="1Min",
                        limit=60,
                        feed="iex",
                    ),
                    headers=headers,
                )
                req_n += 1
                r.raise_for_status()
                for alpaca_sym, bars in (r.json().get("bars") or {}).items():
                    canonical = db.canonical_ticker(alpaca_sym, watchlist)
                    got.add(canonical)
                    n += _store_bars(c, canonical, bars)
            for sym in watchlist:
                if sym in got or req_n >= max_req:
                    continue
                try:
                    r1 = cli.get(
                        "https://data.alpaca.markets/v2/stocks/bars",
                        params=bars_params(
                            symbols=db.alpaca_ticker(sym),
                            timeframe="1Min",
                            limit=60,
                            feed="iex",
                        ),
                        headers=headers,
                    )
                    req_n += 1
                    r1.raise_for_status()
                    for _, bars in (r1.json().get("bars") or {}).items():
                        n += _store_bars(c, sym, bars)
                        got.add(sym)
                except Exception as exc:
                    log.warning("equity %s: %s", sym, exc)
    except Exception as exc:
        db.set_health(c, health_component, "fail", str(exc))
        return
    minute_total = _record_alpaca_request(req_n)
    # AM1: distinguish partial (some syms missing) from full ok — previously any bars → "ok".
    if n and len(got) < len(watchlist):
        status = "partial"
    elif n:
        status = "ok"
    else:
        status = "empty"
    db.set_health(
        c,
        health_component,
        status,
        f"{len(got)}/{len(watchlist)} syms · {n} bars · feed=iex · alpaca_req={req_n}/min={minute_total}",
    )


def pull_daily_ret(c, watchlist: list[str]) -> None:
    """RET 1D = (quote.price − quote.previousClose)/previousClose。最新价只读 src=fmp_quote。"""
    now = int(time.time())
    last_map = {
        sym: cl
        for sym, cl in c.execute(
            "SELECT b.symbol, b.c FROM bars b "
            "JOIN (SELECT symbol, MAX(ts) mts FROM bars WHERE src='fmp_quote' GROUP BY symbol) m "
            "ON b.symbol=m.symbol AND b.ts=m.mts AND b.src='fmp_quote'"
        ).fetchall()
    }
    prev_map = {}
    try:
        prev_map = {
            sym: float(pc)
            for sym, pc in c.execute(
                "SELECT symbol, prev_close FROM intraday_quotes WHERE prev_close IS NOT NULL AND prev_close > 0"
            ).fetchall()
        }
    except Exception:
        prev_map = {}
    filled = 0
    missing: list[str] = []
    for sym in watchlist:
        canonical = db.canonical_ticker(sym, watchlist)
        last = last_map.get(canonical)
        prev_close = prev_map.get(canonical)
        if last is not None and prev_close:
            c.execute(
                "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
                (now, canonical, "ret_1d", (float(last) - prev_close) / prev_close),
            )
            filled += 1
        else:
            missing.append(sym)

    # ---- Alpaca 备份(缺 previousClose 的票;最新价仍只用 fmp_quote)----
    if missing and ALPACA_KEY and ALPACA_SECRET:
        headers = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}
        start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")
        try:
            with httpx.Client(timeout=20) as cli:
                alpaca_syms = list(dict.fromkeys(db.alpaca_ticker(s) for s in missing))
                bars_map: dict[str, list] = {}
                r = cli.get(
                    "https://data.alpaca.markets/v2/stocks/bars",
                    params=bars_params(
                        symbols=",".join(alpaca_syms),
                        timeframe="1Day",
                        start=start,
                        limit=5,
                        feed="iex",
                    ),
                    headers=headers,
                )
                r.raise_for_status()
                bars_map.update(r.json().get("bars") or {})
                for sym in missing:
                    ak = db.alpaca_ticker(sym)
                    if len(bars_map.get(ak) or bars_map.get(sym) or []) >= 2:
                        continue
                    r1 = cli.get(
                        "https://data.alpaca.markets/v2/stocks/bars",
                        params=bars_params(
                            symbols=ak,
                            timeframe="1Day",
                            start=start,
                            limit=5,
                            feed="iex",
                        ),
                        headers=headers,
                    )
                    r1.raise_for_status()
                    bars_map.update(r1.json().get("bars") or {})
                for alpaca_sym, bars in bars_map.items():
                    if len(bars) < 2:
                        continue
                    canonical = db.canonical_ticker(alpaca_sym, watchlist)
                    prev_close = float(bars[1]["c"])
                    last = last_map.get(canonical)
                    if last is None or not prev_close:
                        continue
                    c.execute(
                        "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
                        (now, canonical, "ret_1d", (float(last) - prev_close) / prev_close),
                    )
                    filled += 1
        except Exception as exc:
            log.warning("daily ret alpaca backup: %s", exc)
    if filled:
        db.set_health(c, "data_daily_ret", "ok", f"{filled} syms · ret_1d refreshed")
    else:
        db.set_health(c, "data_daily_ret", "fail", "no symbols filled (FMP+Alpaca)")
        return


def compute_heat_factors(c, watchlist: list[str], now: int | None = None) -> None:
    """快循环(60s):quote 快照 5 分钟窗 RET 5M + RVOL 量能门。单写入者。"""
    import heat_rvol

    now = int(now if now is not None else time.time())
    n = 0
    rvol_n = 0
    for sym in watchlist:
        win = c.execute(
            "SELECT ts, c FROM bars WHERE symbol=? AND src='fmp_quote' AND ts>=? ORDER BY ts ASC",
            (sym, now - heat_rvol.RET5M_WINDOW_S),
        ).fetchall()
        val = heat_rvol.ret_5m_from_quote_window([(int(t), float(cl)) for t, cl in win])
        if val is not None:
            c.execute(
                "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
                (now, sym, "ret_5m", float(val)),
            )
            n += 1
        vol_rows = c.execute(
            "SELECT v FROM bars WHERE symbol=? AND src='fmp_quote' ORDER BY ts DESC LIMIT ?",
            (sym, heat_rvol.RVOL_LOOKBACK),
        ).fetchall()
        vols = [float(r[0] or 0) for r in vol_rows][::-1]
        rvol, gate, neg = heat_rvol.rvol_from_cumulative(vols)
        gate = heat_rvol.apply_session_gate(gate, now)
        if neg:
            log.warning("heat rvol negative volume delta %s (quote cumulative reset)", sym)
        c.execute(
            "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
            (now, sym, "rvol_gate", heat_rvol.encode_gate(gate)),
        )
        if rvol is not None:
            c.execute(
                "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
                (now, sym, "rvol", float(rvol)),
            )
            rvol_n += 1
    db.set_health(
        c, "factor_heat", "ok" if n else "empty",
        f"{n} syms · ret_5m quote-window 300s · rvol={rvol_n}",
    )


def compute_factors(c, watchlist: list[str]) -> None:
    now = int(time.time())
    n = 0
    for sym in watchlist:
        rows = c.execute(
            "SELECT c FROM bars WHERE symbol=? ORDER BY ts DESC LIMIT 31", (sym,)
        ).fetchall()
        closes = [r[0] for r in rows][::-1]
        if len(closes) < 6:
            continue
        rets = [(closes[i + 1] - closes[i]) / closes[i] for i in range(len(closes) - 1) if closes[i]]
        factors = {
            "ret_30m": (closes[-1] - closes[0]) / closes[0] if closes[0] else 0.0,
            "vol_1m": statistics.pstdev(rets[-30:]) if len(rets) >= 2 else 0.0,
            "range_pos": ((closes[-1] - min(closes)) / (max(closes) - min(closes))
                          if max(closes) != min(closes) else 0.5),
        }
        for name, val in factors.items():
            c.execute(
                "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
                (now, sym, name, float(val)),
            )
        n += 1
    db.set_health(c, "factor", "ok" if n else "empty", f"{n} syms · v0 set")


def compute_option_factors(c, watchlist: list[str]) -> None:
    """Theta Options VALUE → 日频 options 因子(net_gex / atm_iv / total_oi)。

    Theta EOD 17:15 ET 生成 normalized report;盘中拉返回最新可用(昨日)。
    每日每 symbol 只拉一次(factors 表 gate:当日已有 net_gex 即跳过)。
    Theta 不可达/无数据 → 跳过,不报错(独立系统,不阻塞股票因子)。
    """
    import datetime as _dt
    import theta_options
    _ET = _dt.timezone(_dt.timedelta(hours=-4))  # EDT; options 因子日频,1d lag 可接受
    now_et = _dt.datetime.now(_ET)
    # 永远用最近的前一交易日:theta 当日 EOD 需指定 expiration(expiration=* 对当日 400),
    # 且当日 normalized EOD 17:15 ET 才生成。用昨日 EOD 稳定(与 OWS theta_loader 一致)。
    theta_date = now_et.date() - _dt.timedelta(days=1)
    while theta_date.weekday() >= 5:
        theta_date = theta_date - _dt.timedelta(days=1)
    date_s = theta_date.isoformat()
    now = int(time.time())
    ok = 0
    for sym in watchlist:
        # gate: 当日已写过 net_gex → 跳过(日频)
        exists = c.execute(
            "SELECT 1 FROM factors WHERE symbol=? AND name='net_gex' AND ts>=?",
            (sym, int(_dt.datetime.combine(theta_date, _dt.time.min, _ET).timestamp())),
        ).fetchone()
        if exists:
            ok += 1
            continue
        spot_row = c.execute(
            "SELECT c FROM bars WHERE symbol=? ORDER BY ts DESC LIMIT 1", (sym,)
        ).fetchone()
        spot = float(spot_row[0]) if spot_row and spot_row[0] else None
        try:
            fac = theta_options.fetch_option_factors(sym, date_s, spot)
        except Exception as exc:
            log.warning("theta_options %s: %s", sym, exc)
            continue
        if not fac:
            continue
        for name, val in (
            ("net_gex", fac.get("net_gex")),
            ("atm_iv", fac.get("atm_iv")),
            ("total_oi", fac.get("total_oi")),
            ("gamma_flip", fac.get("gamma_flip")),
        ):
            if val is None:
                continue
            c.execute(
                "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
                (now, sym, name, float(val) if isinstance(val, (int, float)) else 0.0),
            )
        ok += 1
    if ok:
        db.set_health(c, "theta_options", "ok", f"{ok} syms · {date_s} · gex/iv/oi")
    else:
        db.set_health(c, "theta_options", "empty", f"no syms · {date_s}(Theta 不可达或无数据)")


def build_decisions(c) -> None:
    gs = db.grid_store()
    if gs is None:
        db.set_health(c, "grid_store", "fail", "grid_store.db 不可达")
        return
    try:
        today = dt.datetime.now(ET).strftime("%Y-%m-%d")
        made = 0
        audit: dict = {"date": today, "windows": {}}
        for window in ("AM", "PM"):
            payload = db.latest_bfs(gs, today, window)
            if not payload:
                audit["windows"][window] = {"candidates": 0, "decisions": 0, "filtered": [], "scan_event_id": None}
                continue
            eid = payload.get("_event_id")
            if scan_quarantine.is_quarantined(event_id=eid, date=today, window=window):
                audit["windows"][window] = {
                    "candidates": len(payload.get("rows") or []),
                    "decisions": 0,
                    "filtered": [],
                    "scan_event_id": eid,
                    "quarantine": True,
                    "quarantine_reason": "missing bid/ask chain unverified",
                }
                continue
            rows = (payload.get("rows") or [])[:10]
            wl = db.resolve_watchlist()
            rec = bfs_surface.reconcile_bfs_rows(rows, wl)
            # A6: only watchlist-surface rows become decisions. Previously every
            # bid/ask row (incl. off-heat / off-watchlist symbols) was inserted and
            # exposed via /api/decisions as a paper decision — misleading signals.
            decision_rows = rec["surface_rows"]
            filtered = list(rec.get("surface_filtered") or [])
            # also account for missing-bid/ask rows in the audit trail
            for row in rows:
                if row.get("bid") is None or row.get("ask") is None:
                    s = row.get("sym")
                    if s and not any(f.get("sym") == s for f in filtered):
                        filtered.append({"symbol": s, "reason": "missing bid/ask"})
            win_made = 0
            for row in decision_rows:
                bid, ask = row.get("bid"), row.get("ask")
                entry = round((float(bid) + float(ask)) / 2, 2)
                contract = f"{row.get('sym')} C{row.get('strike')} {row.get('expiry')} ({row.get('dte')}d)"
                c.execute(
                    "INSERT OR REPLACE INTO decisions(ts, trade_date, window, scan_event_id, symbol, contract, entry, stop, target, meta) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (int(time.time()), today, window, payload.get("_event_id"), row.get("sym"), contract,
                     entry, round(entry * (1 - STOP_PCT), 2), round(entry * (1 + TARGET_PCT), 2),
                     json.dumps({"score": row.get("score"), "delta": row.get("delta"), "iv": row.get("iv"),
                                 "params": f"v0 stop-{int(STOP_PCT*100)}%/target+{int(TARGET_PCT*100)}% 未回测"},
                                ensure_ascii=False)),
                )
                win_made += 1
                made += 1
            audit["windows"][window] = {
                "candidates": rec["raw_n"],
                "decisions": win_made,
                "filtered": filtered,
                "scan_event_id": payload.get("_event_id"),
                "reconcile": {
                    "raw_n": rec["raw_n"],
                    "surface_n": rec["surface_n"],
                    "excluded": rec["excluded"],
                    "store_skipped_n": rec["store_skipped_n"],
                },
            }
        db.set_health(c, "grid_store", "ok", f"BFS→decisions {made} rows(v0 参数未回测)")
        db.set_health(c, "decisions_audit", "ok", json.dumps(audit, ensure_ascii=False)[:400])
    finally:
        gs.close()


def _integrity_or_sleep(tick_s: int) -> bool:
    """Return False if integrity failed (caller should skip cycle)."""
    integrity_err = db.check_integrity(quick=True)
    if not integrity_err:
        return True
    log.error("platform.db integrity failed: %s", integrity_err)
    c = db.conn()
    try:
        db.set_health(c, "platform_db", "corrupt", integrity_err[:400])
        c.commit()
    finally:
        c.close()
    _stop.wait(tick_s)
    return False


def run_heat_cycle() -> None:
    """60s:热力 watchlist 1Min + RET 5M;与慢循环隔离 try/except。"""
    started = time.time()
    if not _integrity_or_sleep(HEAT_TICK_SECONDS):
        return
    c = db.conn()
    try:
        db.set_health(c, "platform_db", "ok", "quick_check pass")
        import heat_nomination
        import fmp_heat_quotes

        heat = heat_nomination.resolve_heat(refresh=True, conn=c)
        wl = list(heat.get("watchlist") or [])
        fmp_heat_quotes.pull_fmp_heat_quotes(c, wl)
        compute_heat_factors(c, wl)
        nom = heat.get("nomination") or {}
        n_scan = sum(1 for _s, src in (heat.get("sources") or {}).items() if src in ("scan", "bfs", "movers"))
        n_wl = sum(1 for _s, src in (heat.get("sources") or {}).items() if src == "watchlist")
        detail = (
            f"heat wl={n_wl}+scan={n_scan}/{nom.get('cap', 8)} · "
            f"overflow={nom.get('overflow_n', 0)} · "
            f"{','.join(wl[:10])}{'…' if len(wl) > 10 else ''}"
        )
        db.set_health(c, "watchlist", "ok", detail)
        _degraded = _collect_degraded_components(c)
        if _degraded:
            db.set_health(c, "worker_heat", "partial", "degraded: " + ",".join(_degraded))
        else:
            db.set_health(c, "worker_heat", "ok", f"heat {int(time.time() - started)}s · {len(wl)} syms")
        db.set_health(c, "worker", "ok", f"heat {int(time.time() - started)}s")
        db.set_health(c, "heat_locked", "ok" if _heat_locked_n == 0 else "fail", f"n={_heat_locked_n}")
        c.commit()
    except Exception as exc:
        locked = _note_heat_locked("run_heat_cycle", exc)
        log.exception("heat cycle error")
        try:
            db.set_health(
                c,
                "worker_heat",
                "fail",
                f"locked n={_heat_locked_n}" if locked else "heat cycle exception — see logs",
            )
            db.set_health(c, "heat_locked", "fail" if _heat_locked_n else "ok", f"n={_heat_locked_n}")
            c.commit()
        except Exception:
            pass
    finally:
        c.close()


def run_scan_cycle() -> None:
    """300s:movers/EOD/BFS/因子全量;与快循环隔离 try/except。"""
    started = time.time()
    if not _integrity_or_sleep(SCAN_TICK_SECONDS):
        return
    wl: list[str] = []
    c = db.conn()
    try:
        db.set_health(c, "platform_db", "ok", "quick_check pass")
        try:
            import build_universe as _bu

            _u = _bu.refresh_if_stale(max_age_h=24.0)
            if _u == "refreshed":
                log.info("universe_market refreshed")
            db.set_health(c, "universe_market", "ok" if _u != "failed" else "fail", _u)
        except Exception as _uexc:
            log.warning("universe_market refresh: %s", _uexc)
            db.set_health(c, "universe_market", "fail", str(_uexc)[:200])
        import heat_nomination

        heat = heat_nomination.resolve_heat(refresh=False, conn=c)
        wl = list(heat.get("watchlist") or [])
        hedge = db.resolve_hedge_symbols()
        equity_syms = list(dict.fromkeys(wl + [s for s in hedge if s not in wl]))
        hedge_only = [s for s in hedge if s not in wl]
        pull_crypto(c)
        if hedge_only:
            pull_equities(c, hedge_only, health_component="data_equity")
        compute_factors(c, equity_syms)
        compute_option_factors(c, equity_syms)
        pull_daily_ret(c, equity_syms)
        try:
            import fault_heat_runner
            _fh = fault_heat_runner.tick(c, equity_syms)
            if _fh.get("actions"):
                log.info("fault heat: %s", _fh["actions"])
        except Exception as _exc:
            log.warning("fault heat runner failed: %s", _exc)
        build_decisions(c)
        _degraded = _collect_degraded_components(c)
        if _degraded:
            db.set_health(c, "worker_scan", "partial", "degraded: " + ",".join(_degraded))
        else:
            db.set_health(c, "worker_scan", "ok", f"scan_face {int(time.time() - started)}s · movers_pending")
        c.commit()
    except Exception:
        log.exception("scan cycle error")
        try:
            db.set_health(c, "worker_scan", "fail", "scan cycle exception — see logs")
            c.commit()
        except Exception:
            pass
    finally:
        c.close()

    # factor_truth 可跑 100s+ — 独立连接,避免与 heat 线程争 platform.db 写锁
    if not wl:
        return
    import factor_truth
    budget = max(30.0, float(SCAN_TICK_SECONDS) - (time.time() - started) - 15.0)
    c2 = db.conn()
    try:
        factor_truth.run_factor_truth_cycle(c2, wl, budget_s=budget)
        _st = factor_truth.write_txn_stats()
        db.set_health(
            c2,
            "write_txn",
            "ok" if float(_st["max_s"]) < 2.0 else "amber",
            f"max={_st['max_s']:.3f}s n={_st['n']}",
        )
        _degraded2 = _collect_degraded_components(c2)
        if _degraded2:
            db.set_health(c2, "worker_scan", "partial", "degraded: " + ",".join(_degraded2))
        else:
            db.set_health(c2, "worker_scan", "ok", f"scan {int(time.time() - started)}s")
        c2.commit()
    except Exception as exc:
        log.warning("factor_truth: %s", exc)
        try:
            db.set_health(c2, "factor_truth", "fail", str(exc)[:200])
            db.set_health(c2, "worker_scan", "partial", "factor_truth failed")
            c2.commit()
        except Exception:
            pass
    finally:
        c2.close()


def _heat_loop() -> None:
    while not _stop.is_set():
        t0 = time.time()
        try:
            run_heat_cycle()
        except Exception:
            log.exception("heat loop outer error")
        _stop.wait(max(5, HEAT_TICK_SECONDS - (time.time() - t0)))


def _scan_loop() -> None:
    while not _stop.is_set():
        t0 = time.time()
        try:
            run_scan_cycle()
        except Exception:
            log.exception("scan loop outer error")
        _stop.wait(max(5, SCAN_TICK_SECONDS - (time.time() - t0)))


def main() -> None:
    log.info(
        "worker up · heat=%ss · scan=%ss · base=%s · crypto=%s",
        HEAT_TICK_SECONDS,
        SCAN_TICK_SECONDS,
        db.BASE_WATCHLIST,
        CRYPTO_PRODUCTS,
    )
    threading.Thread(target=_heat_loop, name="worker-heat", daemon=True).start()
    _scan_loop()


if __name__ == "__main__":
    main()
