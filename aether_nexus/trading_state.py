"""Build GET /api/state JSON for AETHER TRADING v12.2 (signalfirst + heattable)."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _load_is_quarantined():
    import importlib.util
    from pathlib import Path

    sq_path = Path(__file__).resolve().parent / "scan_quarantine.py"
    spec = importlib.util.spec_from_file_location("_aether_scan_quarantine", sq_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("scan_quarantine module missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.is_quarantined


_is_quarantined = _load_is_quarantined()


def _load_bfs_surface():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent / "bfs_surface.py"
    spec = importlib.util.spec_from_file_location("_aether_bfs_surface", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("bfs_surface module missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bfs_surface = _load_bfs_surface()

GRID_STORE_PATH = os.getenv("GRID_STORE_PATH", "")
CONF_RANK = {"高置信": 3, "试探性": 2, "观察": 1}
HEAT_STALE_S = int(os.getenv("HEAT_STALE_S", "600"))
DEFAULT_WATCHLIST = "NVDA,PLTR,AMZN,NOW"


def _surface_exclude() -> frozenset[str]:
    return bfs_surface.surface_exclude()


def _filtered_from_reconcile(entry: dict[str, Any]) -> dict:
    reason = entry.get("reason") or "filtered"
    labels = {
        "surface_exclude": "surface_exclude · SURFACE_DENY",
        "not_in_watchlist": "not_in_watchlist · env watchlist",
        "missing bid/ask": "missing bid/ask",
    }
    return {
        "sym": entry.get("sym"),
        "side": "—",
        "score": entry.get("score"),
        "reason": labels.get(reason, reason),
    }


def _env_watchlist(pulse: dict | None) -> list[str]:
    wl = (pulse or {}).get("watchlist") or []
    if wl:
        return [str(s).upper() for s in wl]
    return [s.strip().upper() for s in os.getenv("WATCHLIST", DEFAULT_WATCHLIST).split(",") if s.strip()]


def _in_env_watchlist(sym: str, wl: list[str]) -> bool:
    return str(sym or "").upper() in set(wl)


def _age_str(age_s: int | None) -> str:
    if age_s is None:
        return "—"
    if age_s < 90:
        return f"{age_s}s"
    if age_s < 5400:
        return f"{round(age_s / 60)}m"
    return f"{round(age_s / 3600)}h"


def _http_json(url: str, timeout: float = 2.5) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def _grid_conn(db_path: str) -> sqlite3.Connection | None:
    if not db_path or not os.path.isfile(db_path):
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _bfs_window_ts_bounds(date_str: str, window: str) -> tuple[float, float]:
    day = dt.date.fromisoformat(date_str)
    if window == "AM":
        start = dt.datetime.combine(day, dt.time(9, 35), tzinfo=ET)
        end = dt.datetime.combine(day, dt.time(12, 5), tzinfo=ET)
    else:
        start = dt.datetime.combine(day, dt.time(15, 25), tzinfo=ET)
        end = dt.datetime.combine(day, dt.time(16, 30), tzinfo=ET)
    return start.timestamp(), end.timestamp()


def _latest_bfs(gs: sqlite3.Connection, date_str: str, window: str) -> dict[str, Any] | None:
    row = gs.execute(
        "SELECT id, payload FROM events WHERE source='aether' AND kind='aether_scan' "
        "AND json_extract(payload,'$.label')='BFS sp500' "
        "AND json_extract(payload,'$.date')=? AND json_extract(payload,'$.window')=? "
        "ORDER BY id DESC LIMIT 1",
        (date_str, window),
    ).fetchone()
    if not row:
        ts_lo, ts_hi = _bfs_window_ts_bounds(date_str, window)
        row = gs.execute(
            "SELECT id, payload FROM events WHERE source='aether' AND kind='aether_scan' "
            "AND json_extract(payload,'$.label')='BFS sp500' "
            "AND ts>=? AND ts<? ORDER BY id DESC LIMIT 1",
            (ts_lo, ts_hi),
        ).fetchone()
    if not row:
        return None
    payload = json.loads(row[1])
    payload["_event_id"] = row[0]
    payload.setdefault("date", date_str)
    payload.setdefault("window", window)
    return payload


def _row_side(row: dict) -> str:
    d = str(row.get("dir") or row.get("side") or "CALL").upper()
    return "PUT" if d in ("PUT", "P", "空") else "CALL"


def _signal_from_row(row: dict) -> dict | None:
    bid, ask = row.get("bid"), row.get("ask")
    if bid is None or ask is None:
        return None
    entry = round((float(bid) + float(ask)) / 2, 2)
    spread = row.get("spread")
    if spread is None and bid and ask:
        mid = (float(bid) + float(ask)) / 2
        spread = round((float(ask) - float(bid)) / mid * 100, 1) if mid else None
    sym = row.get("sym") or row.get("symbol")
    side = _row_side(row)
    strike = row.get("strike")
    expiry = row.get("expiry")
    dte = row.get("dte")
    contract = None
    if sym and strike:
        cp = "C" if side == "CALL" else "P"
        contract = f"{sym} {cp}{strike}"
        if expiry:
            contract += f" {expiry}"
        if dte is not None:
            contract += f" ({dte}d)"
    return {
        "sym": sym,
        "side": side,
        "delta": row.get("delta"),
        "iv": row.get("iv"),
        "spread": spread,
        "entry": entry,
        "stop": round(entry * 0.7, 2),
        "target": round(entry * 1.6, 2),
        "score": row.get("score"),
        "contract": contract,
        "note": row.get("note") or "",
        "ts": row.get("ts"),
        "volume": row.get("volume"),
        "open_interest": row.get("open_interest"),
        "oi_source": row.get("oi_source"),
        "oi_unverified": row.get("oi_unverified"),
    }


def _filtered_from_row(row: dict) -> dict:
    bid, ask = row.get("bid"), row.get("ask")
    reason = "missing bid/ask" if bid is None or ask is None else str(row.get("reason") or "filtered")
    return {
        "sym": row.get("sym") or row.get("symbol"),
        "side": _row_side(row),
        "score": row.get("score"),
        "reason": reason,
    }


def _window_block(
    gs: sqlite3.Connection | None,
    *,
    date_str: str,
    window: str,
    pulse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    note_waiting = "等待 AM 窗口 · ~09:45 ET" if window == "AM" else "等待 PM 窗口 · ~15:35 ET"
    if gs is None:
        return {"status": "waiting", "scanId": None, "note": note_waiting, "signals": [], "filtered": []}
    payload = _latest_bfs(gs, date_str, window)
    if not payload:
        return {"status": "waiting", "scanId": None, "note": note_waiting, "signals": [], "filtered": []}
    eid = payload.get("_event_id")
    scan_id = f"#{eid}" if eid else None
    rows = payload.get("rows") or []
    if _is_quarantined(event_id=eid, date=date_str, window=window):
        return {
            "status": "quarantine",
            "scanId": scan_id,
            "note": "本轮查证中 · 不作数 · 解除权:Lyra",
            "signals": [],
            "filtered": [_filtered_from_reconcile(f) for f in bfs_surface.reconcile_bfs_rows(rows, _env_watchlist(pulse))["filtered"]],
            "reconcile": bfs_surface.reconcile_bfs_rows(rows, _env_watchlist(pulse)),
        }
    wl = _env_watchlist(pulse)
    rec = bfs_surface.reconcile_bfs_rows(rows, wl, surface_deny=_surface_exclude())
    signals = []
    for row in rec["surface_rows"]:
        sig = _signal_from_row(row)
        if sig:
            signals.append(sig)
    # 页面宣称「按 score 降序」— 信号必须真排序
    signals.sort(
        key=lambda s: (
            0 if s.get("score") is not None else 1,
            -(float(s["score"]) if s.get("score") is not None else 0.0),
            str(s.get("sym") or ""),
        ),
    )
    filtered = [_filtered_from_reconcile(f) for f in rec["surface_filtered"]]
    return {
        "status": "scanned",
        "scanId": scan_id,
        "note": "",
        "signals": signals,
        "filtered": filtered,
        "reconcile": {
            "raw_n": rec["raw_n"],
            "surface_n": rec["surface_n"],
            "excluded": rec["excluded"],
        },
    }


def _split_note(note: str) -> tuple[str, str]:
    text = (note or "").replace(" | ", "，").replace("|", "，").strip()
    m = re.split(r"风险[：:]", text, maxsplit=1)
    if len(m) == 2:
        return m[0].strip(), f"风险：{m[1].strip()}"
    return text, ""


def _brief_block(
    gs: sqlite3.Connection | None,
    date_str: str,
    pulse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """DeepSeek 盘前简报已从 TRADING 决策面撤下(2026-08-06)。

    保留 brief 字段形状以兼容旧客户端;不再读 aether_premarket_deepseek。
    """
    _ = (gs, pulse)  # unused — brief retired
    return {
        "slot": "盘前简报",
        "date": date_str[5:] if len(date_str) >= 10 else date_str,
        "compile": "—",
        "compile_ts": None,
        "lane": "retired",
        "rows": [],
        "retired": True,
        "retired_reason": "deepseek_brief_removed_from_trading_surface",
    }


def _decode_rvol_gate(value: Any) -> str:
    if value is None:
        return "warming"
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("pass", "fail", "warming", "auction"):
            return v
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "warming"
    if n <= -1.5:
        return "auction"
    if n <= -0.5:
        return "warming"
    if n >= 0.5:
        return "pass"
    return "fail"


def _heat_leader_cards(heat: list[dict]) -> list[dict[str, Any]]:
    """First-screen = heat 表顶行; 只从 gate=pass 取。"""
    equity = [
        h for h in heat
        if h.get("sym") and not str(h["sym"]).endswith("-USD")
        and h.get("ret5m") is not None
        and str(h.get("rvol_gate") or "") == "pass"
    ]
    if equity:
        top, col, label = equity[0], "ret5m", "RET 5M"
    else:
        equity = [
            h for h in heat
            if h.get("sym") and not str(h["sym"]).endswith("-USD") and h.get("ret1d") is not None
        ]
        if not equity:
            return []
        top, col, label = equity[0], "ret1d", "RET 1D"

    val = top.get(col)
    dir_txt = "多" if val is not None and val > 0 else ("空" if val is not None and val < 0 else "观察")
    view = f"{label} {val:+.2f}%" if val is not None else f"{label} —"
    last = top.get("last")
    return [{
        "sym": top["sym"],
        "dir": dir_txt,
        "conf": f"{label} #1",
        "view": view,
        "risk": f"最新 ${last}" if last is not None else "",
        "note": f"热力表 {label} 排名第一",
        "contract": None,
        "entry": last,
        "stop": None,
        "ts": top.get("quote_ts"),
        col: val,
        "ret5m": top.get("ret5m"),
        "ret1d": top.get("ret1d"),
        "bfs": top.get("bfs"),
        "src": "heat",
        "src_label": "来源=热力表",
        "rank_col": col,
    }]


def _crypto_from_pulse(pulse: dict | None) -> list[dict[str, Any]]:
    if not pulse:
        return []
    out: list[dict[str, Any]] = []
    for t in pulse.get("crypto") or []:
        extra = t.get("extra") or {}
        fac_ret = None
        if extra.get("open_24h") and t.get("price"):
            fac_ret = ((float(t["price"]) - float(extra["open_24h"])) / float(extra["open_24h"])) * 100
        age_s = t.get("age_s")
        out.append({
            "sym": t["symbol"],
            "last": t.get("price"),
            "ret1d": fac_ret,
            "bid": extra.get("bid"),
            "ask": extra.get("ask"),
            "age_s": age_s,
            "stale": age_s is not None and age_s > HEAT_STALE_S,
        })
    out.sort(
        key=lambda x: (x.get("ret1d") is not None, x.get("ret1d") if x.get("ret1d") is not None else float("-inf")),
        reverse=True,
    )
    return out


def _heat_from_pulse(pulse: dict | None) -> tuple[list[dict], dict[str, Any]]:
    meta = (pulse or {}).get("meta") or {}
    refresh_s = int(meta.get("refresh_s") or 300)
    if not pulse:
        return [], {
            "quote_asof_et": None,
            "pipeline_delay_s": None,
            "refresh_s": refresh_s,
            "stale_s": HEAT_STALE_S,
            "factor_label": "vs env",
        }
    out: list[dict] = []
    for e in pulse.get("equity") or []:
        sym = e["symbol"]
        fac = e.get("factors") or {}
        age_s = e.get("age_s")
        ret1d = fac.get("ret_1d")
        stale = age_s is not None and age_s > HEAT_STALE_S
        if ret1d is None and stale:
            ret1d = None
        mom_pct = fac.get("mom_20d_pct")
        rev_pct = fac.get("rev_5d_pct")
        vol_pct = fac.get("vol_20d_pct")
        out.append({
            "sym": sym,
            "bfs": bool(e.get("bfs")),
            "source": e.get("source") or ("bfs" if e.get("bfs") else "watchlist"),
            "last": e.get("last"),
            "ret1d": (ret1d * 100) if ret1d is not None else None,
            "ret5m": (fac.get("ret_5m") or 0) * 100 if fac.get("ret_5m") is not None else None,
            "rvol": fac.get("rvol"),
            "rvol_gate": _decode_rvol_gate(fac.get("rvol_gate")),
            "ret30m": (fac.get("ret_30m") or 0) * 100 if fac.get("ret_30m") is not None else None,
            "mom_20d_pct": mom_pct,
            "rev_5d_pct": rev_pct,
            "vol_20d_pct": vol_pct,
            "bid": None,
            "ask": None,
            "quote_ts": e.get("ts"),
            "age_s": age_s,
            "stale": stale or (ret1d is None and e.get("last") is not None),
            "env_order": e.get("env_order"),
        })
    for t in pulse.get("crypto") or []:
        extra = t.get("extra") or {}
        fac_ret = None
        age_s = t.get("age_s")
        if extra.get("open_24h") and t.get("price"):
            fac_ret = ((float(t["price"]) - float(extra["open_24h"])) / float(extra["open_24h"])) * 100
        stale = age_s is not None and age_s > HEAT_STALE_S
        out.append({
            "sym": t["symbol"],
            "bfs": False,
            "last": t.get("price"),
            "ret1d": fac_ret,
            "ret5m": None,
            "ret30m": None,
            "bid": extra.get("bid"),
            "ask": extra.get("ask"),
            "quote_ts": t.get("ts"),
            "age_s": age_s,
            "stale": stale or (fac_ret is None),
            "env_order": 999,
        })
    heat_meta = {
        "quote_asof_et": meta.get("quote_asof_et"),
        "data_age_s": meta.get("data_age_s"),
        "pipeline_delay_s": meta.get("data_age_s"),
        "refresh_s": int(meta.get("heat_refresh_s") or meta.get("refresh_s") or 60),
        "heat_refresh_s": int(meta.get("heat_refresh_s") or meta.get("refresh_s") or 60),
        "scan_refresh_s": int(meta.get("scan_refresh_s") or 300),
        "stale_s": HEAT_STALE_S,
        "factor_label": ((pulse or {}).get("factorTruthMeta") or {}).get("label") or "vs env",
        "factor_asof_et": meta.get("quote_asof_et"),
        "store_write_ts": meta.get("store_write_ts"),
        "store_age_s": meta.get("store_age_s"),
        "face_period_s": meta.get("heat_face_period_s") or meta.get("face_period_s") or 60,
        "heat_face_period_s": meta.get("heat_face_period_s") or 60,
        "scan_face_period_s": meta.get("scan_refresh_s") or 300,
        "age_level": meta.get("age_level"),
        "next_tick_in_s": meta.get("heat_next_tick_in_s") or meta.get("next_tick_in_s"),
        "heat_next_tick_in_s": meta.get("heat_next_tick_in_s"),
        "scan_next_tick_in_s": meta.get("scan_next_tick_in_s"),
    }
    return out, heat_meta


def _daily_movers_from_pulse(pulse: dict | None) -> tuple[dict[str, list], dict[str, Any]]:
    dm = (pulse or {}).get("dailyMovers") or {}
    gainers = dm.get("gainers") or dm.get("items") or []
    losers = dm.get("losers") or []
    meta = (pulse or {}).get("meta") or {}
    stale = False
    movers_age = meta.get("movers_age_s")
    if movers_age is not None and movers_age > HEAT_STALE_S * 3:
        stale = True
    if dm.get("status") not in (None, "ok"):
        stale = True

    def _norm(rows):
        out = []
        for r in rows:
            out.append({
                "sym": r.get("sym"),
                "last": r.get("last"),
                "ret1d": r.get("ret1d"),
                "volume": r.get("volume"),
                "asof_ts": r.get("asof_ts"),
                "bfs": bool(r.get("bfs")),
                "stale": stale or bool(r.get("stale")),
            })
        return out

    dm_meta = {
        "asof_et": dm.get("asof_et"),
        "asof_ts": dm.get("asof_ts"),
        "status": dm.get("status") or "waiting",
        "universe": dm.get("universe"),
        "with_data": dm.get("with_data"),
        "stale": stale,
    }
    return {"gainers": _norm(gainers), "losers": _norm(losers)}, dm_meta


def _health_from_platform() -> list[dict]:
    plat = _http_json(os.getenv("PLATFORM_HEALTH_URL", "http://127.0.0.1:8600/api/health"))
    if not plat:
        return [
            {"name": "加密", "ok": False, "age": "—"},
            {"name": "美股", "ok": False, "age": "—"},
            {"name": "名单", "ok": False, "age": "—"},
            {"name": "因子", "ok": False, "age": "—"},
        ]
    labels = {
        "data_crypto": "加密",
        "data_equity": "美股",
        "watchlist": "名单",
        "factor": "因子",
    }
    comps = plat.get("components") or {}
    out = []
    for key, label in labels.items():
        st = (comps.get(key) or {}).get("status")
        out.append({
            "name": label,
            "ok": st in ("ok", "closed"),
            "status": st or "",
            "age": _age_str((comps.get(key) or {}).get("age_s")),
        })
    return out


def _env_block(pulse: dict | None) -> dict:
    wl = (pulse or {}).get("watchlist") or []
    if not wl:
        wl = [s.strip().upper() for s in os.getenv("WATCHLIST", DEFAULT_WATCHLIST).split(",") if s.strip()]
    bfs = {e.get("symbol") for e in (pulse or {}).get("equity") or [] if e.get("bfs")}
    pinned = sum(1 for s in wl if s in bfs)
    return {"count": len(wl), "pinned": pinned, "list": ", ".join(wl)}


def _postmortem_from_window(w: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in w.get("filtered") or []:
        out.append({
            "sym": row.get("sym"),
            "score": row.get("score"),
            "kill_reason": row.get("reason") or row.get("kill_reason") or "filtered",
        })
    return out


def _brief_headline(brief: dict[str, Any]) -> str | None:
    rows = brief.get("rows") or []
    if not rows:
        return None
    r = rows[0]
    sym = r.get("sym") or "—"
    note = str(r.get("note") or "")
    snippet = (note[:48] + "…") if len(note) > 48 else note
    return f"{sym} · {r.get('dir', '—')} · {r.get('conf', '—')} · {snippet}" if snippet else f"{sym} · {r.get('dir', '—')} · {r.get('conf', '—')}"


def build_state(*, grid_store_path: str | None = None) -> dict[str, Any]:
    today = dt.datetime.now(ET).strftime("%Y-%m-%d")
    db_path = grid_store_path or GRID_STORE_PATH
    gs = _grid_conn(db_path) if db_path else None
    pulse = _http_json(os.getenv("PLATFORM_PULSE_URL", "http://127.0.0.1:8600/api/pulse"))
    try:
        am = _window_block(gs, date_str=today, window="AM", pulse=pulse)
        pm = _window_block(gs, date_str=today, window="PM", pulse=pulse)
        decisions = len(am.get("signals") or []) + len(pm.get("signals") or [])
        brief = _brief_block(gs, today, pulse=pulse)
        skip = _surface_exclude()
        if brief.get("rows"):
            brief = {
                **brief,
                "rows": [r for r in brief["rows"] if str(r.get("sym") or "").upper() not in skip],
            }
        heat, heat_meta = _heat_from_pulse(pulse)
        heat = [h for h in heat if str(h.get("sym") or "").upper() not in skip]
        # P1+G2: pass × RET 5M, then warming/auction, then fail; 空沉底
        _gr = {"pass": 0, "warming": 1, "auction": 1, "fail": 2}
        heat = sorted(
            heat,
            key=lambda h: (
                _gr.get(str(h.get("rvol_gate") or "warming"), 1),
                0 if h.get("ret5m") is not None else 1,
                -(float(h["ret5m"]) if h.get("ret5m") is not None else 0.0),
                int(h.get("env_order") or 999),
            ),
        )
        daily_movers, daily_movers_meta = _daily_movers_from_pulse(pulse)
        signal_cards = _heat_leader_cards(heat)
        crypto = _crypto_from_pulse(pulse)
        postmortem = _postmortem_from_window(am) + _postmortem_from_window(pm)
        pm_note = pm.get("note") or ""
        pm_window = pm_note.replace("等待 PM 窗口 · ", "").replace("等待 PM 窗口 ", "") if pm_note else "~15:35 ET"
        # store 最后写入: grid_store 最新事件 ts(本面读周期 12s,与 heat tick 300s 分层)
        store_write_ts = None
        if gs is not None:
            try:
                row = gs.execute("SELECT MAX(ts) FROM events").fetchone()
                store_write_ts = int(row[0]) if row and row[0] is not None else None
            except Exception:
                store_write_ts = None
        face_period_s = 12  # v12 poll; 节奏不动,仅可见性
        now = int(dt.datetime.now(dt.timezone.utc).timestamp())
        store_age_s = (now - store_write_ts) if store_write_ts else None
        age_level = "unknown"
        if store_age_s is not None:
            age_level = "amber" if store_age_s > face_period_s * 2 else "ok"
        sync_age = {
            "store_write_ts": store_write_ts,
            "store_age_s": store_age_s,
            "face_period_s": face_period_s,
            "age_level": age_level,
            "read_ts": now,
            "heat_next_tick_in_s": heat_meta.get("next_tick_in_s"),
            "heat_refresh_s": heat_meta.get("refresh_s"),
        }
        return {
            "version": "12.2",
            "date": today,
            "health": _health_from_platform(),
            "env": _env_block(pulse),
            "am": am,
            "pm": pm,
            "decisions": decisions,
            "brief": brief,
            "briefCards": [],
            "signalCards": signal_cards,
            "dailyMovers": daily_movers.get("gainers") or [],
            "dailyMoversLosers": daily_movers.get("losers") or [],
            "dailyMoversMeta": daily_movers_meta,
            "heat": heat,
            "heatMeta": heat_meta,
            "syncAge": sync_age,
            "scan_candidates": (pulse or {}).get("scan_candidates") or [],
            "crypto": crypto,
            "postmortem": postmortem,
            "postmortemSummary": {
                "window": "AM",
                "total": (am.get("reconcile") or {}).get("raw_n", 0),
                "killed": len(am.get("filtered") or []),
            } if am.get("filtered") else None,
            "pmCountdown": pm_note,
            "pmWindow": pm_window,
            "quarantine": am.get("status") == "quarantine",
        }
    finally:
        if gs is not None:
            gs.close()
