"""Alpha Platform · Phase 0 · app.py — API + 静态仪表盘。
CHANGELOG: v0.1 (2026-07-24, Fable) endpoints: /api/health /api/pulse /api/bfs /api/decisions"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import time
from zoneinfo import ZoneInfo

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

import db
import jobs as jobs_mod
import market_session
import platform_state
import scan_quarantine

ET = ZoneInfo("America/New_York")
app = FastAPI(title="Alpha Platform", version="0.1")


@app.get("/api/state")
def api_state():
    if os.getenv("PLATFORM_STATE_DOWN") == "1":
        raise HTTPException(503, "state down (mock fallback test)")
    return platform_state.build_state(
        health_payload=health(),
        pulse_payload=pulse(),
        decisions_payload=decisions(),
    )


@app.get("/api/health")
def health():
    integrity_err = db.check_integrity(quick=True)
    c = db.conn()
    try:
        rows = c.execute("SELECT component, ts, status, detail FROM health").fetchall()
    finally:
        c.close()
    now = int(time.time())
    components = {
        r[0]: {"ts": r[1], "age_s": now - r[1], "status": r[2], "detail": r[3]} for r in rows
    }
    if integrity_err:
        components["platform_db"] = {
            "ts": now,
            "age_s": 0,
            "status": "corrupt",
            "detail": integrity_err[:400],
        }
    if not market_session.is_rth():
        prev = components.get("data_equity") or {}
        components["data_equity"] = {
            "ts": int(prev.get("ts") or now),
            "age_s": now - int(prev.get("ts") or now),
            "status": "closed",
            "detail": prev.get("detail") or "session closed",
        }
    return {"now": now, "components": components}


@app.get("/api/daily_movers")
def daily_movers(direction: str = "up"):
    import factor_truth

    c = db.conn()
    try:
        factor_truth.ensure_schema(c)
        return factor_truth.movers_for_api(c, direction=direction)
    finally:
        c.close()


_MOVERS_CACHE: dict = {"ts": 0.0, "data": None}
_MOVERS_TTL = max(30.0, float(os.getenv("MOVERS_CACHE_TTL", "60")))


def _movers_cached(now: int) -> dict:
    """A4: cached daily movers — recompute at most every _MOVERS_TTL seconds,
    not on every 2s WS tick. Daily bars don't move intra-tick."""
    if _MOVERS_CACHE["data"] is not None and (now - _MOVERS_CACHE["ts"]) < _MOVERS_TTL:
        return _MOVERS_CACHE["data"]
    import factor_truth

    c2 = db.conn()
    try:
        factor_truth.ensure_schema(c2)
        sp500 = factor_truth.load_sp500_symbols()
        bfs = set(db.bfs_candidate_symbols())
        movers_full = factor_truth._movers_from_daily_bars(c2, sp500, bfs) if sp500 else {}
        def _norm_mover_rows(rows):
            out = []
            for r in rows or []:
                if not isinstance(r, dict):
                    continue
                row = dict(r)
                row.setdefault("symbol", row.get("sym"))
                row.setdefault("chg_pct", row.get("ret1d"))
                out.append(row)
            return out
        movers = {
            "gainers": _norm_mover_rows(movers_full.get("gainers")),
            "losers": _norm_mover_rows(movers_full.get("losers")),
            "asof_et": movers_full.get("asof_et"),
            "asof_ts": movers_full.get("asof_ts"),
            "status": movers_full.get("status", "waiting"),
            "universe": movers_full.get("universe"),
            "with_data": movers_full.get("with_data"),
        }
        movers_meta = c2.execute(
            "SELECT ts, status, detail FROM health WHERE component='daily_movers'"
        ).fetchone()
        ft_row = c2.execute(
            "SELECT ts, status, detail FROM health WHERE component='factor_truth'"
        ).fetchone()
    finally:
        c2.close()
    movers_age = (now - int(movers_meta[0])) if movers_meta else None
    if movers_meta and movers_meta[1] != "ok":
        movers = {**movers, "status": movers_meta[1], "detail": movers_meta[2]}
    _MOVERS_CACHE["ts"] = float(now)
    _MOVERS_CACHE["data"] = {"movers": movers, "movers_age": movers_age, "ft_row": ft_row}
    return _MOVERS_CACHE["data"]


@app.get("/api/pulse")
def pulse():
    # A4: movers computation walks full SP500 (~500 symbols × 2 SQL) — cache it so
    # a 2s WS tick doesn't re-run the scan every pulse. TTL defaults 60s.
    integrity_err = db.check_integrity(quick=True)
    if integrity_err:
        raise HTTPException(503, f"platform.db corrupt: {integrity_err[:200]}")
    heat = db.resolve_heat_meta()
    watchlist = list(heat.get("watchlist") or [])
    sources = dict(heat.get("sources") or {})
    scan_candidates = list(heat.get("scan_candidates") or [])
    nomination = dict(heat.get("nomination") or {})
    bfs_heads = set(db.bfs_candidate_symbols()) & set(watchlist)
    c = db.conn()
    try:
        ticks = c.execute(
            "SELECT t.symbol, t.price, t.ts, t.extra FROM ticks t "
            "JOIN (SELECT symbol, MAX(id) mid FROM ticks GROUP BY symbol) m ON t.id=m.mid"
        ).fetchall()
        factors = c.execute(
            "SELECT f.symbol, f.name, f.value, f.ts FROM factors f "
            "JOIN (SELECT symbol, name, MAX(ts) mts FROM factors GROUP BY symbol, name) m "
            "ON f.symbol=m.symbol AND f.name=m.name AND f.ts=m.mts"
        ).fetchall()
        bars = c.execute(
            "SELECT b.symbol, b.c, b.ts, b.src FROM bars b "
            "JOIN (SELECT symbol, MAX(ts) mts FROM bars WHERE src='fmp_quote' GROUP BY symbol) m "
            "ON b.symbol=m.symbol AND b.ts=m.mts AND b.src='fmp_quote'"
        ).fetchall()
        try:
            crosscheck = {
                r[0]: {
                    "stale": bool(r[1]),
                    "lag_s": r[2],
                    "delta_pct": r[3],
                    "alpaca_last": r[4],
                    "alpaca_bid": r[5],
                    "alpaca_ask": r[6],
                    "detail": r[7],
                }
                for r in c.execute(
                    "SELECT symbol, stale, lag_s, delta_pct, alpaca_last, alpaca_bid, alpaca_ask, detail "
                    "FROM heat_crosscheck"
                ).fetchall()
            }
        except Exception:
            crosscheck = {}
        worker_row = c.execute(
            "SELECT ts FROM health WHERE component='worker' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        heat_row = c.execute(
            "SELECT ts FROM health WHERE component='worker_heat' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        scan_row = c.execute(
            "SELECT ts FROM health WHERE component='worker_scan' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    finally:
        c.close()
    now = int(time.time())
    heat_tick_s = max(30, int(os.getenv("HEAT_TICK_SECONDS", "60")))
    scan_tick_s = max(60, int(os.getenv("SCAN_TICK_SECONDS", os.getenv("TICK_SECONDS", "300"))))
    tick_s = scan_tick_s  # legacy refresh_s = slow scan period

    fmap: dict[str, dict] = {}
    fts: dict[str, int] = {}
    for sym, name, value, ts in factors:
        fmap.setdefault(sym, {})[name] = value
        fts[sym] = max(fts.get(sym, 0), int(ts or 0))
    bar_map = {s: (cl, ts, src) for s, cl, ts, src in bars}
    equity = []
    deny = set(db.SURFACE_DENY)
    # 股权 asof 不得被 crypto tick 抬新(曾误导「行情新鲜」而热力仍冻早盘)
    equity_quote_ts = 0
    crypto_quote_ts = 0
    for i, sym in enumerate(watchlist):
        if sym in deny:
            continue
        cl, ts, bar_src = bar_map.get(sym, (None, None, None))
        qts = int(ts or 0) or None  # FMP quote timestamp（数据龄 = now − qts）
        if qts:
            equity_quote_ts = max(equity_quote_ts, qts)
        cc = crosscheck.get(sym) or {}
        stale = bool(cc.get("stale")) or (qts is None)
        src = sources.get(sym) or ("bfs" if sym in bfs_heads else "watchlist")
        equity.append({
            "symbol": sym,
            "last": cl,
            "ts": qts,
            "quote_src": bar_src or "fmp_quote",
            "age_s": (now - qts) if qts else None,
            "data_age_s": (now - qts) if qts else None,
            "stale": stale,
            "crosscheck": cc if cc else None,
            "env_order": i,
            "factors": fmap.get(sym, {}),
            "bfs": sym in bfs_heads,
            "source": src,  # watchlist | bfs | movers
        })
    crypto = []
    for s, p, ts, x in ticks:
        extra = json.loads(x or "{}")
        qts = int(ts or 0)
        crypto_quote_ts = max(crypto_quote_ts, qts)
        crypto.append({
            "symbol": s,
            "price": p,
            "ts": qts or None,
            "age_s": (now - qts) if qts else None,
            "extra": extra,
        })
    data_age_s = None
    if equity:
        row_ages = [e["age_s"] for e in equity if e.get("age_s") is not None]
        if row_ages:
            data_age_s = max(row_ages)
    quote_ts = equity_quote_ts or crypto_quote_ts
    asof_et = (
        dt.datetime.fromtimestamp(equity_quote_ts, tz=ET).strftime("%H:%M:%S")
        if equity_quote_ts
        else (dt.datetime.fromtimestamp(crypto_quote_ts, tz=ET).strftime("%H:%M:%S")
              if crypto_quote_ts
              else dt.datetime.now(ET).strftime("%H:%M:%S"))
    )
    crypto_asof_et = (
        dt.datetime.fromtimestamp(crypto_quote_ts, tz=ET).strftime("%H:%M:%S")
        if crypto_quote_ts
        else None
    )
    import factor_truth

    _mc = _movers_cached(now)
    movers = _mc["movers"]
    movers_age = _mc["movers_age"]
    ft_row = _mc["ft_row"]
    store_write_ts = int(heat_row[0]) if heat_row else (int(worker_row[0]) if worker_row else (quote_ts or 0))
    store_age_s = (now - store_write_ts) if store_write_ts else None
    # 热力面周期 = worker_heat 60s; 超 2× 变琥珀(仪表宪法)
    heat_face_period_s = heat_tick_s
    age_level = "ok"
    if store_age_s is None:
        age_level = "unknown"
    elif store_age_s > heat_face_period_s * 2:
        age_level = "amber"
    # data_stale / data_source: explicit flag so the frontend can refuse to render
    # MOCK data on API failure instead of silently showing stale ticks as fresh.
    # Stale when: worker never ran, ticks older than 2× tick period, or no equity
    # quotes at all. data_source names the degraded component for the banner.
    data_stale = age_level != "ok" or not equity_quote_ts
    data_source = "live"
    if not worker_row:
        data_source = "worker_down"
    elif age_level == "amber":
        data_source = f"stale_{store_age_s}s"
    elif not equity_quote_ts:
        data_source = "no_equity_quotes"
    heat_next_tick_in = None
    scan_next_tick_in = None
    if heat_row:
        elapsed = now - int(heat_row[0])
        heat_next_tick_in = max(0, heat_tick_s - elapsed)
    if scan_row:
        elapsed = now - int(scan_row[0])
        scan_next_tick_in = max(0, scan_tick_s - elapsed)
    next_tick_in = heat_next_tick_in
    return {
        "watchlist": watchlist,
        "sources": sources,
        "scan_candidates": scan_candidates,
        "nomination": nomination,
        "crypto": crypto,
        "equity": equity,
        "dailyMovers": movers,
        "factorTruthMeta": {
            "status": ft_row[1] if ft_row else "waiting",
            "detail": ft_row[2] if ft_row else None,
            "age_s": (now - int(ft_row[0])) if ft_row else None,
            "label": "vs env",
        },
        "meta": {
            "quote_asof_et": asof_et,
            "equity_quote_asof_et": asof_et if equity_quote_ts else None,
            "crypto_quote_asof_et": crypto_asof_et,
            "quote_ts": quote_ts or now,
            "equity_quote_ts": equity_quote_ts or None,
            "crypto_quote_ts": crypto_quote_ts or None,
            "data_age_s": data_age_s,
            "pipeline_delay_s": data_age_s,  # deprecated alias
            "refresh_s": heat_tick_s,
            "heat_refresh_s": heat_tick_s,
            "scan_refresh_s": scan_tick_s,
            "movers_age_s": movers_age,
            "store_write_ts": store_write_ts or None,
            "store_age_s": store_age_s,
            "face_period_s": heat_face_period_s,
            "heat_face_period_s": heat_face_period_s,
            "scan_face_period_s": scan_tick_s,
            "age_level": age_level,
            "next_tick_in_s": next_tick_in,
            "heat_next_tick_in_s": heat_next_tick_in,
            "scan_next_tick_in_s": scan_next_tick_in,
            "read_ts": now,
            "data_stale": data_stale,
            "data_source": data_source,
        },
    }


@app.get("/api/bfs")
def bfs():
    gs = db.grid_store()
    if gs is None:
        return {"available": False}
    try:
        today = dt.datetime.now(ET).strftime("%Y-%m-%d")
        out = {"available": True, "date": today, "windows": {}}
        for window in ("AM", "PM"):
            payload = db.latest_bfs(gs, today, window)
            if payload:
                out["windows"][window] = {
                    "event_id": payload.get("_event_id"),
                    "universe_size": payload.get("universe_size"),
                    "status": payload.get("status"),
                    "rows": (payload.get("rows") or [])[:10],
                }
        return out
    finally:
        gs.close()


@app.get("/api/decisions")
def decisions():
    c = db.conn()
    try:
        today = dt.datetime.now(ET).strftime("%Y-%m-%d")
        rows = c.execute(
            "SELECT window, symbol, contract, entry, stop, target, meta, ts FROM decisions "
            "WHERE trade_date=? ORDER BY window, symbol",
            (today,),
        ).fetchall()
        audit_row = c.execute(
            "SELECT detail FROM health WHERE component='decisions_audit'"
        ).fetchone()
    finally:
        c.close()
    audit = {}
    if audit_row and audit_row[0]:
        try:
            audit = json.loads(audit_row[0])
        except json.JSONDecodeError:
            audit = {}
    bfs_out = bfs()
    q = scan_quarantine.status_payload()
    am_rows = len((bfs_out.get("windows") or {}).get("AM", {}).get("rows") or [])
    header_contract = {
        "am_hits": am_rows,
        "am_isolation_badge": bool(q.get("active") and am_rows > 0),
        "isolation_suffix": "隔离中" if q.get("active") else "",
    }
    return {
        "date": today,
        "paper_only": True,
        "quarantine": q,
        "header_contract": header_contract,
        "rows": [
            {
                "window": w,
                "symbol": s,
                "contract": ct,
                "entry": e,
                "stop": st,
                "target": tg,
                "meta": json.loads(m or "{}"),
                "ts": ts,
            }
            for w, s, ct, e, st, tg, m, ts in rows
        ],
        "audit": audit,
        "bfs": bfs_out,
    }


@app.post("/api/jobs/factor_replay")
def start_job():
    watchlist = db.resolve_watchlist()
    if not watchlist:
        raise HTTPException(400, "watchlist empty")
    return {"job_id": jobs_mod.start_factor_replay(watchlist)}


@app.post("/api/factory/propose")
def factory_propose(body: dict):
    idea = str(body.get("idea") or "").strip()
    if not idea:
        raise HTTPException(400, "idea required")
    test = bool(body.get("test"))
    budget_hint = str(body.get("budget_hint") or "std")
    try:
        import factory_pipeline as fp

        return fp.propose_factor(idea, test=test, budget_hint=budget_hint)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        msg = str(exc)
        if "推理槽满" in msg or "429" in msg or "gateway_busy" in msg or "8501 推理槽满" in msg:
            raise HTTPException(429, msg) from exc
        raise HTTPException(502, f"Grid factory: {exc}") from exc


@app.post("/api/factory/review/{draft_id}")
def factory_review(draft_id: int):
    import factory_pipeline as fp

    return {"job_id": fp.start_review(draft_id)}


@app.get("/api/factory/drafts")
def factory_drafts(limit: int = 20):
    import factory_pipeline as fp

    return {"drafts": fp.list_drafts(limit=limit)}


@app.get("/api/factory/queue")
def factory_queue(status: str | None = None):
    import factory_pipeline as fp

    return {"proposals": fp.list_proposals(status=status)}


@app.post("/api/factory/decide")
def factory_decide(body: dict):
    proposal_id = body.get("proposal_id")
    decision = body.get("decision")
    if proposal_id is None:
        raise HTTPException(400, "proposal_id required")
    try:
        import factory_pipeline as fp

        return fp.decide_proposal(int(proposal_id), str(decision or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def job_status(job_id: int):
    c = db.conn_jobs()
    try:
        row = c.execute("SELECT kind, status, pct, detail FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        c.close()
    if not row:
        return {"found": False}
    return {"found": True, "kind": row[0], "status": row[1], "pct": row[2], "detail": row[3]}


@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    """每 2s 推 snapshot(health/pulse/decisions)+ 自游标以来的新 job_events。"""
    await ws.accept()
    cursor = 0
    c0 = db.conn_jobs()
    try:
        row = c0.execute("SELECT COALESCE(MAX(id),0) FROM job_events").fetchone()
        cursor = row[0] if row else 0
    finally:
        c0.close()
    try:
        while True:
            c = db.conn_jobs()
            try:
                events = c.execute(
                    "SELECT id, job_id, ts, pct, kind, payload FROM job_events WHERE id>? ORDER BY id LIMIT 500",
                    (cursor,),
                ).fetchall()
            finally:
                c.close()
            if events:
                cursor = events[-1][0]
            await ws.send_json(
                {
                    "type": "snapshot",
                    "health": health(),
                    "pulse": pulse(),
                    "decisions": decisions(),
                    "bfs": bfs(),
                    "job_events": [
                        {
                            "id": e[0],
                            "job_id": e[1],
                            "ts": e[2],
                            "pct": e[3],
                            "kind": e[4],
                            "payload": json.loads(e[5] or "{}"),
                        }
                        for e in events
                    ],
                }
            )
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # A2: surface stream errors to the client instead of silent exit
        try:
            await ws.send_json({"type": "error", "reason": f"{exc.__class__.__name__}: {exc}"})
        except Exception:
            pass
        return


APPDIST = Path("/appdist")
_LEGACY = Path("/frontend/index.html")
_CONSOLE_V11 = Path(os.getenv("CONSOLE_V11_HTML", str(Path(__file__).resolve().parent.parent / "frontend-static" / "console_v11.html")))
_PLATFORM_MAIN = (os.getenv("PLATFORM_MAIN") or "v11").strip().lower()


def _nocache() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _app_url_prefix(request: Request) -> str:
    """Tailscale Serve /alpha → 浏览器 URL 带 /alpha；8600 后端仍见 /app。"""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    if host.endswith(".ts.net"):
        return "/alpha/app"
    ref = request.headers.get("referer") or ""
    fwd = request.headers.get("x-forwarded-uri") or request.headers.get("x-original-uri") or ""
    if "/alpha/" in ref or fwd.startswith("/alpha/"):
        return "/alpha/app"
    return "/app"


def _react_index_response(request: Request) -> Response:
    html_path = APPDIST / "index.html"
    if not html_path.is_file():
        raise HTTPException(404, "react app not built")
    base = _app_url_prefix(request)
    html = html_path.read_text(encoding="utf-8")
    html = html.replace('src="./assets/', f'src="{base}/assets/')
    html = html.replace('href="./assets/', f'href="{base}/assets/')
    body = html.encode("utf-8")
    build = "2026-07-27-factory-router"
    headers = {**_nocache(), "Content-Length": str(len(body)), "X-Alpha-UI-Build": build}
    content = b"" if request.method == "HEAD" else body
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers=headers,
    )


def _react_asset_response(rest: str, request: Request) -> Response:
    path = (APPDIST / "assets" / rest).resolve()
    root = (APPDIST / "assets").resolve()
    if not str(path).startswith(str(root)) or not path.is_file():
        raise HTTPException(404)
    body = path.read_bytes()
    media = "application/javascript" if rest.endswith(".js") else "text/css" if rest.endswith(".css") else "application/octet-stream"
    headers = {**(_nocache() if rest.endswith((".js", ".css")) else {}), "Content-Length": str(len(body))}
    content = b"" if request.method == "HEAD" else body
    return Response(content=content, media_type=media, headers=headers)


@app.get("/legacy")
def legacy_dashboard():
    if not _LEGACY.is_file():
        raise HTTPException(404)
    return FileResponse(_LEGACY)


@app.get("/app/console_v11.html")
@app.head("/app/console_v11.html")
def console_v11_html(request: Request):
    if not _CONSOLE_V11.is_file():
        raise HTTPException(404, "console_v11.html missing")
    body = _CONSOLE_V11.read_bytes()
    headers = {**_nocache(), "Content-Length": str(len(body)), "X-Alpha-UI-Build": "2026-07-31-heat-sort-v3"}
    content = b"" if request.method == "HEAD" else body
    return Response(content=content, media_type="text/html; charset=utf-8", headers=headers)


def _entry_app_url(request: Request) -> str:
    """Tailscale /alpha 无尾斜杠时相对 app/ 会落到 gateway /app/ (404) — 须绝对路径。"""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    if host.endswith(".ts.net"):
        return f"{proto}://{host}/alpha/app/"
    return "/app/"


@app.get("/")
@app.head("/")
def index(request: Request):
    return RedirectResponse(url=_entry_app_url(request), status_code=302)


if APPDIST.is_dir():
    @app.get("/app")
    @app.head("/app")
    def react_app_noslash():
        # 禁止 StaticFiles 绝对重定向 /app/ (会丢 /alpha 前缀 → 手机 404)
        return RedirectResponse(url="./", status_code=302)

    @app.get("/app/")
    @app.head("/app/")
    def platform_app_index(request: Request):
        """主运维台 — 默认 v1.1(守恒 HTML + hedge[]);React 兜底见 /app/react/。"""
        if _PLATFORM_MAIN == "v11":
            return console_v11_html(request)
        return _react_index_response(request)

    @app.get("/app/react")
    @app.head("/app/react")
    def react_app_react_noslash():
        return RedirectResponse(url="./", status_code=302)

    @app.get("/app/react/")
    @app.head("/app/react/")
    def react_app_index(request: Request):
        return _react_index_response(request)

    @app.get("/app/assets/{rest:path}")
    @app.head("/app/assets/{rest:path}")
    def react_app_assets(rest: str, request: Request):
        return _react_asset_response(rest, request)
