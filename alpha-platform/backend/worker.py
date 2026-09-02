"""Alpha Platform · Phase 0 · worker.py — 数据→因子→决策 循环。"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import statistics
import time
from zoneinfo import ZoneInfo

import httpx

import db
import scan_quarantine
import bfs_surface
from alpaca_bars import bars_params
from factor_truth import fetch_fmp_daily_bars  # 2026-08-17:FMP 主源日线

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
# FMP key 不进 INFO 日志(httpx INFO 会把含 apikey= 的 URL 整行打出;2026-09-02 砥 P0)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("worker")

ET = ZoneInfo("America/New_York")
TICK_SECONDS = max(60, int(os.getenv("TICK_SECONDS", "300")))
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


def pull_equities(c, watchlist: list[str]) -> None:
    if not (ALPACA_KEY and ALPACA_SECRET):
        db.set_health(c, "data_equity", "skipped", "ALPACA_* 未配置")
        return
    headers = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}
    got: set[str] = set()
    n = 0
    try:
        with httpx.Client(timeout=12) as cli:
            alpaca_syms = list(dict.fromkeys(db.alpaca_ticker(s) for s in watchlist))
            # 必须 sort=desc:Alpaca 默认 asc+limit 会吃到会话最旧分钟线
            # (现网判例 2026-08-07:热力/因子冻在 ~10:28 ET,收盘价已到 171 仍显示早盘)
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
            r.raise_for_status()
            for alpaca_sym, bars in (r.json().get("bars") or {}).items():
                canonical = db.canonical_ticker(alpaca_sym, watchlist)
                got.add(canonical)
                n += _store_bars(c, canonical, bars)
            for sym in watchlist:
                if sym in got:
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
                    r1.raise_for_status()
                    for _, bars in (r1.json().get("bars") or {}).items():
                        n += _store_bars(c, sym, bars)
                        got.add(sym)
                except Exception as exc:
                    log.warning("equity %s: %s", sym, exc)
    except Exception as exc:
        db.set_health(c, "data_equity", "fail", str(exc))
        return
    # AM1: distinguish partial (some syms missing) from full ok — previously any bars → "ok".
    if n and len(got) < len(watchlist):
        status = "partial"
    elif n:
        status = "ok"
    else:
        status = "empty"
    db.set_health(c, "data_equity", status, f"{len(got)}/{len(watchlist)} syms · {n} bars · feed=iex")


def pull_daily_ret(c, watchlist: list[str]) -> None:
    """Prev-close → ret_1d factor (当日涨跌%)。FMP 主源,Alpaca 备份(2026-08-17 Lyra 拍板)。"""
    now = int(time.time())
    last_map = {
        sym: cl
        for sym, cl in c.execute(
            "SELECT b.symbol, b.c FROM bars b JOIN (SELECT symbol, MAX(ts) mts FROM bars GROUP BY symbol) m "
            "ON b.symbol=m.symbol AND b.ts=m.mts"
        ).fetchall()
    }
    filled = 0
    missing: list[str] = []
    # ---- FMP 主源(逐票;降序 [0]=最新交易日,[1]=前一交易日)----
    for sym in watchlist:
        bars = fetch_fmp_daily_bars(sym, 5)
        if len(bars) >= 2:
            canonical = db.canonical_ticker(sym, watchlist)
            prev_close = float(bars[1]["c"])
            last = last_map.get(canonical)
            if last is not None and prev_close:
                c.execute(
                    "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
                    (now, canonical, "ret_1d", (float(last) - prev_close) / prev_close),
                )
                filled += 1
            continue
        missing.append(sym)

    # ---- Alpaca 备份(FMP 缺的票)----
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
            "ret_5m": (closes[-1] - closes[-6]) / closes[-6] if closes[-6] else 0.0,
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


def main() -> None:
    log.info("worker up · tick=%ss · base=%s · crypto=%s", TICK_SECONDS, db.BASE_WATCHLIST, CRYPTO_PRODUCTS)
    while True:
        started = time.time()
        integrity_err = db.check_integrity(quick=True)
        if integrity_err:
            log.error("platform.db integrity failed: %s", integrity_err)
            c = db.conn()
            try:
                db.set_health(c, "platform_db", "corrupt", integrity_err[:400])
                c.commit()
            finally:
                c.close()
            time.sleep(TICK_SECONDS)
            continue
        c = db.conn()
        try:
            db.set_health(c, "platform_db", "ok", "quick_check pass")
            import heat_nomination

            # same connection as worker cycle — avoid dual-conn lock on DELETE journal
            heat = heat_nomination.resolve_heat(refresh=True, conn=c)
            wl = list(heat.get("watchlist") or [])
            scan_syms = db.scan_candidate_symbols()
            hedge = db.resolve_hedge_symbols()
            equity_syms = list(dict.fromkeys(wl + [s for s in hedge if s not in wl]))
            pull_crypto(c)
            pull_equities(c, equity_syms)
            compute_factors(c, equity_syms)
            compute_option_factors(c, equity_syms)
            pull_daily_ret(c, equity_syms)
            # 断层热力 V1.2:05:45 定版 / 盘前扫描 / 盘中 H 计算 + F4 30min 刷 + Bark 推送
            try:
                import fault_heat_runner
                _fh = fault_heat_runner.tick(c, equity_syms)
                if _fh.get("actions"):
                    log.info("fault heat: %s", _fh["actions"])
            except Exception as _exc:
                log.warning("fault heat runner failed: %s", _exc)
            nom = heat.get("nomination") or {}
            n_scan = sum(1 for _s, src in (heat.get("sources") or {}).items() if src == "scan")
            n_wl = sum(1 for _s, src in (heat.get("sources") or {}).items() if src == "watchlist")
            detail = (
                f"heat wl={n_wl}+scan={n_scan}/{nom.get('cap', 8)} · "
                f"overflow={nom.get('overflow_n', 0)} · "
                f"{','.join(wl[:10])}{'…' if len(wl) > 10 else ''}"
            )
            db.set_health(c, "watchlist", "ok", detail)
            build_decisions(c)
            # Face tick first — do not let SP500 movers stall heat/scan/quote age.
            # Gate completion on partial failures: if any data/factor/store sub-stage
            # reported non-ok health this cycle, mark worker "partial" instead of
            # "ok" so the console can surface degradation rather than silently
            # showing a green tick over stale/empty data.
            _degraded = _collect_degraded_components(c)
            if _degraded:
                db.set_health(c, "worker", "partial", "degraded: " + ",".join(_degraded))
            else:
                # AM8: face tick commits before factor_truth (movers/percentiles) runs —
                # label it so the console knows movers may lag one cycle, not a clean "ok".
                db.set_health(c, "worker", "ok", f"cycle_face {int(time.time() - started)}s · movers_pending")
            c.commit()

            import factor_truth
            # Leave headroom inside TICK_SECONDS for sleep; movers are skip-fresh.
            budget = max(30.0, float(TICK_SECONDS) - (time.time() - started) - 15.0)
            try:
                factor_truth.run_factor_truth_cycle(c, wl, budget_s=budget)
                _degraded2 = _collect_degraded_components(c)
                if _degraded2:
                    db.set_health(c, "worker", "partial", "degraded: " + ",".join(_degraded2))
                else:
                    db.set_health(c, "worker", "ok", f"cycle {int(time.time() - started)}s")
                c.commit()
            except Exception as exc:
                log.warning("factor_truth: %s", exc)
                db.set_health(c, "factor_truth", "fail", str(exc)[:200])
                db.set_health(c, "worker", "partial", "factor_truth failed")
                c.commit()
        except Exception:
            log.exception("cycle error")
            try:
                db.set_health(c, "worker", "fail", "cycle exception — see logs")
                c.commit()
            except Exception:
                pass
        finally:
            c.close()
        time.sleep(max(5, TICK_SECONDS - (time.time() - started)))


if __name__ == "__main__":
    main()
