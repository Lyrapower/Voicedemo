"""Heat dynamic nomination — deterministic, zero LLM (Lyra 2026-07-31).

heat = optional env WATCHLIST seats (empty = none)
+ same-day BFS 4 + movers 4 (不足互补, 合计 ≤8).
SURFACE_DENY = final veto only. Overflow → scan_candidates（涨榜未进席）.
Scan pool = same ET calendar day only (Lyra 2026-08-24: 禁 T+3 沿用; Friday BFS
cannot occupy Tuesday heat). last_on < today is demoted, not carried.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
SCAN_NOMINATION_CAP = int(os.getenv("HEAT_SCAN_NOMINATION_CAP", "8"))
BFS_SEAT_CAP = int(os.getenv("HEAT_BFS_SEAT_CAP", "4"))
MOVERS_SEAT_CAP = int(os.getenv("HEAT_MOVERS_SEAT_CAP", "4"))
# Kept at 0 and ignored for cutoff: historical env HEAT_NOMINATION_TTL_DAYS=3
# was the T+3 leak. Scan pool is hard same-day; do not honor a longer TTL.
NOMINATION_TTL_TRADING_DAYS = 0

SCHEMA = """
CREATE TABLE IF NOT EXISTS heat_nominations(
  symbol TEXT PRIMARY KEY,
  source TEXT NOT NULL DEFAULT 'scan',
  first_on TEXT NOT NULL,
  last_on TEXT NOT NULL,
  score REAL DEFAULT 0,
  meta TEXT DEFAULT '{}'
);
"""


def ensure_schema(c: sqlite3.Connection) -> None:
    c.executescript(SCHEMA)


def _today_et() -> dt.date:
    return dt.datetime.now(_ET).date()


def trading_days_before(day: dt.date, n: int) -> dt.date:
    d = day
    left = max(0, n)
    while left > 0:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def scan_pool_cutoff(day: dt.date | None = None) -> str:
    """Inclusive last_on floor for scan seats/overflow: ET today, never T+N."""
    return (day or _today_et()).isoformat()


def _bar_day_et(ts: Any) -> dt.date | None:
    if ts is None:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ts), tz=_ET).date()
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _same_day_movers(movers: dict[str, Any] | None, today: dt.date) -> dict[str, Any]:
    """Movers may enter the scan pool only if the daily bar is today's ET date."""
    empty: dict[str, Any] = {"gainers": [], "losers": []}
    if not isinstance(movers, dict):
        return empty
    asof_day = _bar_day_et(movers.get("asof_ts"))
    if asof_day != today:
        return empty

    def keep(rows: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for g in rows or []:
            if isinstance(g, dict) and _bar_day_et(g.get("asof_ts")) == today:
                out.append(g)
        return out

    return {
        "gainers": keep(movers.get("gainers")),
        "losers": keep(movers.get("losers")),
        "asof_ts": movers.get("asof_ts"),
    }


def _collect_bfs_bucket() -> list[tuple[str, float, str]]:
    """BFS/scan rows, score desc. why=bfs. Does not mix movers %."""
    import db

    ranked: list[tuple[str, float, str]] = []
    seen: set[str] = set()
    gs = db.grid_store()
    if gs is None:
        return ranked
    try:
        day = _today_et().strftime("%Y-%m-%d")
        row = gs.execute(
            "SELECT payload FROM events WHERE source='aether' AND kind='aether_scan' "
            "AND json_extract(payload,'$.date')=? "
            "AND COALESCE(json_array_length(json_extract(payload,'$.rows')), 0) > 0 "
            "ORDER BY id DESC LIMIT 1",
            (day,),
        ).fetchone()
        if not row:
            return ranked
        rows = json.loads(row[0]).get("rows") or []
        for r in sorted(rows, key=lambda x: float(x.get("score") or 0), reverse=True):
            sym = str(r.get("sym") or "").upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            ranked.append((sym, float(r.get("score") or 0), "bfs"))
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("heat_nomination bfs bucket failed: %s", exc)
    finally:
        gs.close()
    return ranked


def _collect_movers_bucket(c: sqlite3.Connection, occupied: set[str]) -> list[tuple[str, float, str]]:
    """Same-day movers RET 1D desc. why=movers. Skip names already in occupied."""
    import db

    ranked: list[tuple[str, float, str]] = []
    try:
        import factor_truth

        factor_truth.ensure_schema(c)
        sp500 = factor_truth.load_sp500_symbols()
        bfs = set(db.scan_candidate_symbols())
        movers = factor_truth._movers_from_daily_bars(c, sp500, bfs) if sp500 else {}
        movers = _same_day_movers(movers, _today_et())
        for g in (movers.get("gainers") or [])[:40]:
            sym = str(g.get("symbol") or g.get("sym") or "").upper()
            if not sym or sym in occupied:
                continue
            occupied.add(sym)
            pct = float(g.get("ret1d") or g.get("pct") or g.get("change_pct") or 0)
            ranked.append((sym, pct, "movers"))
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("heat_nomination movers bucket failed: %s", exc)
    return ranked


def _rank_scan_and_movers(c: sqlite3.Connection) -> list[tuple[str, float, str]]:
    """Two buckets, each sorted alone. Fill: BFS 4 + movers 4, short bucket tops up."""
    bfs = _collect_bfs_bucket()
    occupied = {s for s, _, _ in bfs}
    movers = _collect_movers_bucket(c, occupied)
    seats, _overflow = allocate_heat_seats(bfs, movers)
    extra = [(s, sc, w) for s, sc, w in bfs + movers if s not in {x[0] for x in seats}]
    return seats + extra


def allocate_heat_seats(
    bfs: list[tuple[str, float, str]],
    movers: list[tuple[str, float, str]],
    *,
    bfs_cap: int | None = None,
    movers_cap: int | None = None,
    total_cap: int | None = None,
) -> tuple[list[tuple[str, float, str]], list[tuple[str, float, str]]]:
    """各桶自排后取 BFS 前 N + movers 前 M；不足互补。返回 (seats, overflow)."""
    bc = BFS_SEAT_CAP if bfs_cap is None else bfs_cap
    mc = MOVERS_SEAT_CAP if movers_cap is None else movers_cap
    tc = SCAN_NOMINATION_CAP if total_cap is None else total_cap
    take_b = list(bfs[:bc])
    take_m = list(movers[:mc])
    rest_b = list(bfs[bc:])
    rest_m = list(movers[mc:])
    while len(take_b) + len(take_m) < tc:
        if rest_m:
            take_m.append(rest_m.pop(0))
        elif rest_b:
            take_b.append(rest_b.pop(0))
        else:
            break
    overflow = rest_m + rest_b
    return take_b + take_m, overflow


def refresh_nominations(c: sqlite3.Connection) -> dict[str, Any]:
    """Upsert today's top pool into heat_nominations; demote by TTL. Deterministic."""
    import db

    ensure_schema(c)
    today = _today_et()
    today_s = today.isoformat()
    cutoff = scan_pool_cutoff(today)
    deny = set(db.SURFACE_DENY) | set(db.ENV_EXCLUDE)
    base = {s for s in db.BASE_WATCHLIST if s not in deny}

    bfs = [(s, sc, w) for s, sc, w in _collect_bfs_bucket() if s not in deny and s not in base]
    movers = [
        (s, sc, w)
        for s, sc, w in _collect_movers_bucket(c, {x[0] for x in bfs})
        if s not in deny and s not in base
    ]
    seats_t, overflow_t = allocate_heat_seats(bfs, movers)
    pool = seats_t + overflow_t
    kept: list[str] = []
    for sym, score, why in pool:
        src = why if why in ("bfs", "movers") else "bfs"
        row = c.execute(
            "SELECT first_on FROM heat_nominations WHERE symbol=?", (sym,)
        ).fetchone()
        if row:
            c.execute(
                "UPDATE heat_nominations SET last_on=?, score=?, source=?, "
                "meta=? WHERE symbol=?",
                (today_s, score, src, json.dumps({"why": why}, ensure_ascii=False), sym),
            )
        else:
            c.execute(
                "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
                "VALUES(?,?,?,?,?,?)",
                (sym, src, today_s, today_s, score,
                 json.dumps({"why": why}, ensure_ascii=False)),
            )
        kept.append(sym)

    c.execute("DELETE FROM heat_nominations WHERE last_on < ?", (cutoff,))
    if kept:
        q = ",".join("?" * len(kept))
        c.execute("DELETE FROM heat_nominations WHERE symbol NOT IN (%s)" % q, kept)
    else:
        c.execute("DELETE FROM heat_nominations")
    c.commit()

    return {
        "seats": [s for s, _, _ in seats_t],
        "overflow": [
            {
                "symbol": s,
                "source": w,
                "score": sc,
                "last_on": today_s,
                "label": "涨榜未进席" if w == "movers" else "BFS 未进席",
            }
            for s, sc, w in overflow_t
        ],
        "cap": SCAN_NOMINATION_CAP,
        "ttl_trading_days": NOMINATION_TTL_TRADING_DAYS,
        "asof": today_s,
        "seat_sources": {s: w for s, _, w in seats_t},
    }


def _norm_nom_source(src: str) -> str:
    s = (src or "").strip().lower()
    if s in ("bfs", "movers", "watchlist"):
        return s
    if s == "scan":
        return "bfs"
    return "bfs"


def _pack_heat(c, *, refresh: bool) -> dict[str, Any]:
    import db

    deny = set(db.SURFACE_DENY) | set(db.ENV_EXCLUDE)
    base = [s for s in db.BASE_WATCHLIST if s not in deny]
    ensure_schema(c)
    if refresh:
        nom = refresh_nominations(c)
        seat_sources = dict(nom.get("seat_sources") or {})
    else:
        today = _today_et()
        cutoff = scan_pool_cutoff(today)
        active = c.execute(
            "SELECT symbol, score, last_on, source FROM heat_nominations "
            "WHERE last_on >= ? ORDER BY score DESC, symbol ASC",
            (cutoff,),
        ).fetchall()
        bfs: list[tuple[str, float, str]] = []
        movers: list[tuple[str, float, str]] = []
        for sym, score, last_on, src in active:
            if sym in deny or sym in set(base):
                continue
            why = _norm_nom_source(src)
            if why == "movers":
                movers.append((sym, score, "movers"))
            else:
                bfs.append((sym, score, "bfs"))
        seats_t, overflow_t = allocate_heat_seats(bfs, movers)
        nom = {
            "seats": [s for s, _, _ in seats_t],
            "overflow": [
                {
                    "symbol": s,
                    "source": w,
                    "score": sc,
                    "last_on": today.isoformat(),
                    "label": "涨榜未进席" if w == "movers" else "BFS 未进席",
                }
                for s, sc, w in overflow_t
            ],
            "cap": SCAN_NOMINATION_CAP,
            "ttl_trading_days": NOMINATION_TTL_TRADING_DAYS,
            "asof": today.isoformat(),
        }
        seat_sources = {s: w for s, _, w in seats_t}

    seats = [s for s in nom["seats"] if s not in deny]
    out: list[str] = []
    sources: dict[str, str] = {}
    for s in base:
        if s not in sources:
            out.append(s)
            sources[s] = "watchlist"
    for s in seats:
        if s not in sources:
            out.append(s)
            sources[s] = _norm_nom_source(seat_sources.get(s, "bfs"))
    out = out[: len(base) + SCAN_NOMINATION_CAP]
    return {
        "watchlist": out,
        "sources": sources,
        "scan_candidates": nom["overflow"],
        "nomination": {
            "cap": nom["cap"],
            "seats_n": len(seats),
            "overflow_n": len(nom["overflow"]),
            "ttl_trading_days": nom["ttl_trading_days"],
            "asof": nom["asof"],
        },
    }


def resolve_heat(*, refresh: bool = False, conn=None) -> dict[str, Any]:
    """Build heat watchlist + sources + overflow. refresh=True only from worker tick.

    Pass worker's open `conn` when refresh=True to avoid SQLite locked (DELETE journal).
    """
    import db

    if conn is not None:
        return _pack_heat(conn, refresh=refresh)
    c = db.conn()
    try:
        return _pack_heat(c, refresh=refresh)
    finally:
        c.close()
