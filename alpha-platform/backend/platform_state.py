"""Build GET /api/state JSON for ALPHA PLATFORM (DEDUP v1 — 运维台,非决策面克隆)."""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from zoneinfo import ZoneInfo

import db
import heat_rvol
import scan_quarantine
import bfs_surface

ET = ZoneInfo("America/New_York")

HEALTH_LABELS = {
    "data_crypto": "加密",
    "data_equity": "美股",
    "watchlist": "名单",
    "factor": "因子",
    "grid_store": "BFS",
    "worker": "循环",
}


def _age_str(age_s: int | None) -> str:
    if age_s is None:
        return "—"
    if age_s < 90:
        return f"{age_s}s"
    if age_s < 5400:
        return f"{round(age_s / 60)}m"
    return f"{round(age_s / 3600)}h"


def _window_status(
    window: str,
    today: str,
    bfs_windows: dict,
    audit_windows: dict,
) -> tuple[str, int, str | None]:
    aw = audit_windows.get(window) or {}
    bw = bfs_windows.get(window) or {}
    hits = aw.get("candidates")
    if hits is None:
        hits = len(bw.get("rows") or [])
    eid = aw.get("scan_event_id") or bw.get("event_id")
    scan_id = f"#{eid}" if eid else None
    if scan_quarantine.is_quarantined(event_id=eid, date=today, window=window):
        return "quarantine", hits, scan_id
    if not bw and not hits:
        note = "等待 AM 窗口 · ~09:45 ET" if window == "AM" else "等待 PM 窗口 · ~15:35 ET"
        return "waiting", 0, None if window == "AM" else scan_id
    return "scanned", hits, scan_id


def _window_chain(
    window: str,
    today: str,
    bfs_windows: dict,
    audit_windows: dict,
    watchlist: list[str],
) -> dict:
    bw = (bfs_windows.get(window) or {})
    aw = (audit_windows.get(window) or {})
    rows = bw.get("rows") or []
    rec = bfs_surface.reconcile_bfs_rows(rows, watchlist)
    audit_rec = aw.get("reconcile") or {}
    if audit_rec.get("raw_n") is not None:
        rec = {**rec, **{k: audit_rec[k] for k in ("raw_n", "surface_n", "excluded") if k in audit_rec}}
    return rec


def build_state(
    *,
    health_payload: dict,
    pulse_payload: dict,
    decisions_payload: dict,
) -> dict:
    today = dt.datetime.now(ET).strftime("%Y-%m-%d")
    comps = health_payload.get("components") or {}
    now = int(time.time())
    health = []
    for key, label in HEALTH_LABELS.items():
        c = comps.get(key) or {}
        health.append({
            "name": label,
            "ok": c.get("status") in ("ok", "closed"),
            "status": c.get("status") or "",
            "age": _age_str(c.get("age_s")),
        })

    wl = pulse_payload.get("watchlist") or db.resolve_watchlist()
    scan_syms = set(db.scan_candidate_symbols())
    env = {
        "count": len(wl),
        "scan_count": sum(1 for s in wl if s in scan_syms),
        "list": ", ".join(wl),
    }

    audit = decisions_payload.get("audit") or {}
    bfs = decisions_payload.get("bfs") or {}
    aw = audit.get("windows") or {}
    bw = bfs.get("windows") or {}

    am_status, am_hits, am_scan = _window_status("AM", today, bw, aw)
    pm_status, pm_hits, pm_scan = _window_status("PM", today, bw, aw)
    am_chain = _window_chain("AM", today, bw, aw, wl)
    pm_chain = _window_chain("PM", today, bw, aw, wl)
    q = decisions_payload.get("quarantine") or scan_quarantine.status_payload()
    quarantine = bool(q.get("active")) or am_status == "quarantine"

    filtered = []  # DEDUP: 滤除明细只在 8501 决策面机房;platform 不暴露

    fmap: dict[str, dict] = {}
    for e in pulse_payload.get("equity") or []:
        fmap[e["symbol"]] = e.get("factors") or {}

    meta = pulse_payload.get("meta") or {}
    refresh_s = int(meta.get("refresh_s") or 300)
    stale_s = int(os.getenv("HEAT_STALE_S", "600"))

    heat = []
    deny = db.SURFACE_DENY
    for e in pulse_payload.get("equity") or []:
        sym = e["symbol"]
        if sym in deny:
            continue
        fac = fmap.get(sym) or {}
        ret1d = fac.get("ret_1d")
        age_s = e.get("age_s")
        heat.append({
            "sym": sym,
            "bfs": bool(e.get("bfs")),
            "source": e.get("source") or ("bfs" if e.get("bfs") else "watchlist"),
            "last": e.get("last"),
            "ret1d": (ret1d * 100) if ret1d is not None else None,
            "ret5m": (fac.get("ret_5m") or 0) * 100 if fac.get("ret_5m") is not None else None,
            "rvol": fac.get("rvol"),
            "rvol_gate": heat_rvol.decode_gate(fac.get("rvol_gate")),
            "ret30m": (fac.get("ret_30m") or 0) * 100 if fac.get("ret_30m") is not None else None,
            "vol1m": (fac.get("vol_1m") or 0) * 100 if fac.get("vol_1m") is not None else None,
            "bid": None,
            "ask": None,
            "vol": None,
            "age_s": age_s,
            "stale": age_s is not None and age_s > stale_s,
            "env_order": e.get("env_order"),
        })
    for t in pulse_payload.get("crypto") or []:
        extra = t.get("extra") or {}
        age_s = t.get("age_s")
        ret1d = None
        if extra.get("open_24h") and t.get("price"):
            ret1d = ((float(t["price"]) - float(extra["open_24h"])) / float(extra["open_24h"])) * 100
        heat.append({
            "sym": t["symbol"],
            "bfs": False,
            "last": t.get("price"),
            "ret1d": ret1d,
            "ret5m": None,
            "ret30m": None,
            "vol1m": None,
            "bid": extra.get("bid"),
            "ask": extra.get("ask"),
            "vol": extra.get("volume"),
            "age_s": age_s,
            "stale": age_s is not None and age_s > stale_s or ret1d is None,
            "env_order": 999,
        })
    heat_meta = {
        "quote_asof_et": meta.get("quote_asof_et"),
        "data_age_s": meta.get("data_age_s"),
        "pipeline_delay_s": meta.get("data_age_s"),  # deprecated alias
        "refresh_s": int(meta.get("heat_refresh_s") or meta.get("refresh_s") or 60),
        "heat_refresh_s": int(meta.get("heat_refresh_s") or meta.get("refresh_s") or 60),
        "scan_refresh_s": int(meta.get("scan_refresh_s") or 300),
        "stale_s": stale_s,
        "store_write_ts": meta.get("store_write_ts"),
        "store_age_s": meta.get("store_age_s"),
        "face_period_s": meta.get("heat_face_period_s") or meta.get("face_period_s") or 60,
        "heat_face_period_s": meta.get("heat_face_period_s") or 60,
        "scan_face_period_s": meta.get("scan_face_period_s") or 300,
        "age_level": meta.get("age_level"),
        "next_tick_in_s": meta.get("heat_next_tick_in_s") or meta.get("next_tick_in_s"),
        "heat_next_tick_in_s": meta.get("heat_next_tick_in_s"),
        "scan_next_tick_in_s": meta.get("scan_next_tick_in_s"),
    }

    hedge = []
    hedge_syms = db.resolve_hedge_symbols()
    c = db.conn()
    try:
        for sym in hedge_syms:
            bar = c.execute(
                "SELECT c FROM bars WHERE symbol=? ORDER BY ts DESC LIMIT 1", (sym,)
            ).fetchone()
            # AM4: get the latest value PER factor name. Previously `ORDER BY ts DESC
            # LIMIT 4` could mix/duplicate names (e.g. 4 ret_5m rows, missing ret_30m),
            # producing wrong hedge RET values.
            fac_rows = c.execute(
                "SELECT f.name, f.value FROM factors f "
                "JOIN (SELECT name, MAX(ts) mts FROM factors WHERE symbol=? GROUP BY name) m "
                "ON f.symbol=? AND f.name=m.name AND f.ts=m.mts",
                (sym, sym),
            ).fetchall()
            fac = {n: v for n, v in fac_rows}
            if not bar and not fac:
                continue
            hedge.append({
                "sym": sym,
                "last": bar[0] if bar else None,
                "ret5m": (fac.get("ret_5m") or 0) * 100 if fac.get("ret_5m") is not None else None,
                "ret30m": (fac.get("ret_30m") or 0) * 100 if fac.get("ret_30m") is not None else None,
                "vol1m": (fac.get("vol_1m") or 0) * 100 if fac.get("vol_1m") is not None else None,
            })
    finally:
        c.close()

    eq = pulse_payload.get("equity") or []
    breadth = (
        f"{sum(1 for e in eq if (e.get('factors') or {}).get('ret_5m', 0) > 0)}/{len(eq)}"
        if eq else "—"
    )
    btc = next((t.get("price") for t in (pulse_payload.get("crypto") or []) if str(t.get("symbol", "")).startswith("BTC")), None)

    # AM7: default = pass × RET 5M (nulls sink). env 序只作表头切换,不再当默认键。
    import heat_rvol
    heat_sorted = sorted(heat, key=heat_rvol.heat_sort_key)

    return {
        "version": "v0.9-dedup",
        "mode": "paper only · broker=false",
        "date": today,
        "stats": {
            "amStatus": am_status,
            "amHits": am_chain.get("raw_n", am_hits),
            "pmStatus": pm_status,
            "pmHits": pm_chain.get("raw_n", pm_hits),
            "decisions": 0,
            "width5m": breadth,
            "btc": btc,
            "bfsAm": {
                "status": am_status,
                "scanId": am_scan,
                "raw": am_chain.get("raw_n", 0),
                "surface": am_chain.get("surface_n", 0),
                "excluded": am_chain.get("excluded") or [],
                "chain": bfs_surface.format_chain(am_chain),
            },
            "bfsPm": {
                "status": pm_status,
                "scanId": pm_scan,
                "raw": pm_chain.get("raw_n", 0),
                "surface": pm_chain.get("surface_n", 0),
                "excluded": pm_chain.get("excluded") or [],
                "chain": bfs_surface.format_chain(pm_chain),
            },
        },
        "health": health,
        "env": env,
        "signal": {
            "quarantine": quarantine,
            "scanId": am_scan or "#?",
        },
        "heat": heat_sorted,
        "heatMeta": heat_meta,
        "syncAge": {
            "store_write_ts": meta.get("store_write_ts"),
            "store_age_s": meta.get("store_age_s"),
            "face_period_s": meta.get("face_period_s") or refresh_s,
            "age_level": meta.get("age_level"),
            "read_ts": meta.get("read_ts"),
            "heat_next_tick_in_s": meta.get("next_tick_in_s"),
            "heat_refresh_s": refresh_s,
        },
        "scan_candidates": pulse_payload.get("scan_candidates") or [],
        "hedge": hedge,
    }
