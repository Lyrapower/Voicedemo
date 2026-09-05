"""Alpha Platform · Phase 0 · db.py — platform.db schema + helpers.
CHANGELOG: v0.1 (2026-07-24, Fable) initial: ticks/bars/factors/decisions/health."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import datetime as dt
from zoneinfo import ZoneInfo

DB_PATH = os.getenv("PLATFORM_DB", "/data/platform.db")
_DIRECT_WRITE_OK = os.getenv("PLATFORM_DB_DIRECT_WRITE") == "1"
_API_PROCESS = os.getenv("ALPHA_PLATFORM_API_PROCESS") == "1"


def assert_db_writer(context: str = "write") -> None:
    """T1: platform.db writes only from api/worker container processes."""
    if _API_PROCESS or _DIRECT_WRITE_OK:
        return
    if DB_PATH.startswith("/tmp") or "pytest" in sys.modules:
        return
    raise RuntimeError(
        f"Direct platform.db {context} blocked on host (path={DB_PATH}). "
        "Use http://127.0.0.1:8600/api/factory/* or set PLATFORM_DB_DIRECT_WRITE=1 for emergency."
    )
_ET = ZoneInfo("America/New_York")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks(
  id INTEGER PRIMARY KEY, ts INTEGER, market TEXT, symbol TEXT, price REAL, extra TEXT);
CREATE INDEX IF NOT EXISTS ix_ticks ON ticks(symbol, ts);
CREATE TABLE IF NOT EXISTS bars(
  id INTEGER PRIMARY KEY, ts INTEGER, symbol TEXT, o REAL, h REAL, l REAL, c REAL, v REAL,
  UNIQUE(symbol, ts) ON CONFLICT REPLACE);
CREATE TABLE IF NOT EXISTS factors(
  id INTEGER PRIMARY KEY, ts INTEGER, symbol TEXT, name TEXT, value REAL,
  UNIQUE(symbol, name, ts) ON CONFLICT REPLACE);
CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY, ts INTEGER, trade_date TEXT, window TEXT, scan_event_id INTEGER,
  symbol TEXT, contract TEXT, entry REAL, stop REAL, target REAL, meta TEXT,
  UNIQUE(trade_date, window, symbol) ON CONFLICT REPLACE);
CREATE TABLE IF NOT EXISTS health(
  component TEXT PRIMARY KEY, ts INTEGER, status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS heat_push_log(
  symbol TEXT, fault_type TEXT, fault_level REAL, push_kind TEXT,
  last_push_ts REAL, last_value REAL,
  PRIMARY KEY(symbol, fault_type, fault_level, push_kind));
CREATE TABLE IF NOT EXISTS daily_bars(
  id INTEGER PRIMARY KEY, ts INTEGER, symbol TEXT, o REAL, h REAL, l REAL, c REAL, v REAL, src TEXT,
  UNIQUE(symbol, ts) ON CONFLICT REPLACE);
CREATE INDEX IF NOT EXISTS ix_daily_bars_sym ON daily_bars(symbol, ts);
CREATE TABLE IF NOT EXISTS platform_state(
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bar_fetch_log(
  symbol TEXT PRIMARY KEY, attempted_ts INTEGER NOT NULL, got_ts INTEGER);
CREATE TABLE IF NOT EXISTS intraday_quotes(
  symbol TEXT PRIMARY KEY, price REAL, prev_close REAL, volume REAL, quote_ts INTEGER, fetched_ts INTEGER NOT NULL);
"""


def conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    _configure_sqlite(c)
    c.executescript(SCHEMA)
    try:
        c.execute("ALTER TABLE bars ADD COLUMN src TEXT")
    except sqlite3.OperationalError:
        pass
    return c


def _configure_sqlite(c: sqlite3.Connection) -> None:
    """Named volume, single side (VM only). WAL: readers never block the writer.
    connect(timeout=30) is sqlite3_busy_timeout — set before the first PRAGMA so journal_mode itself can wait.
    Bind-mount era forbade WAL: see platform-db-concurrent-write-redline v3 rule 3."""
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA foreign_keys=ON")


def check_integrity(*, quick: bool = True) -> str | None:
    """Return None if ok, else human-readable failure (for health probes)."""
    pragma = "quick_check" if quick else "integrity_check"
    c = sqlite3.connect(DB_PATH, timeout=10)
    try:
        _configure_sqlite(c)
        row = c.execute(f"PRAGMA {pragma}").fetchone()
        if row and row[0] == "ok":
            return None
        return str(row[0] if row else f"{pragma} failed")
    except sqlite3.Error as exc:
        return str(exc)
    finally:
        c.close()


def remove_wal_sidecars() -> None:
    """Delete stale -wal/-shm after recovery or journal_mode switch."""
    for suffix in ("-wal", "-shm"):
        p = f"{DB_PATH}{suffix}"
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def set_health(c: sqlite3.Connection, component: str, status: str, detail: str = "") -> None:
    c.execute(
        "INSERT INTO health(component, ts, status, detail) VALUES(?,?,?,?) "
        "ON CONFLICT(component) DO UPDATE SET ts=excluded.ts, status=excluded.status, detail=excluded.detail",
        (component, int(time.time()), status, detail[:400]),
    )


def grid_store() -> sqlite3.Connection | None:
    """既有 grid_store.db,只读挂载;不可用时返回 None(平台自身照常跑)。"""
    path = os.getenv("GRID_STORE_PATH", "/griddata/grid_store.db")
    if not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


BASE_WATCHLIST = [
    s.strip().upper()
    for s in os.getenv("WATCHLIST", "").split(",")
    if s.strip()
]
SURFACE_DENY = frozenset(
    s.strip().upper()
    for s in os.getenv("SURFACE_DENY", "TSLA,GOOGL,AEHR").split(",")
    if s.strip()
)
ENV_EXCLUDE = frozenset(
    s.strip().upper()
    for s in os.getenv("ENV_EXCLUDE", "T").split(",")
    if s.strip()
)
HEDGE_SYMBOLS = [
    s.strip().upper()
    for s in os.getenv("HEDGE_SYMBOLS", "VIXY,SQQQ,GLD,TLT,UUP").split(",")
    if s.strip()
]
# Alpaca IEX 有时只认 GOOG;落库仍用 BFS/canonical 符号(GOOGL)
ALPACA_SYMBOL = {"GOOGL": "GOOG"}


def resolve_hedge_symbols() -> list[str]:
    """Env HEDGE_SYMBOLS — 避险观察池,走 Alpaca IEX,不注入 heat watchlist."""
    return list(HEDGE_SYMBOLS)


def scan_candidate_symbols(*, date_str: str | None = None) -> list[str]:
    """今日最新 aether_scan 候选(Pool scan / BFS sp500 等), score 降序, deny 过滤."""
    gs = grid_store()
    if gs is None:
        return []
    day = date_str or dt.datetime.now(_ET).strftime("%Y-%m-%d")
    try:
        row = gs.execute(
            "SELECT payload FROM events WHERE source='aether' AND kind='aether_scan' "
            "AND json_extract(payload,'$.date')=? "
            "AND COALESCE(json_array_length(json_extract(payload,'$.rows')), 0) > 0 "
            "ORDER BY id DESC LIMIT 1",
            (day,),
        ).fetchone()
        if not row:
            return []
        rows = json.loads(row[0]).get("rows") or []
        rows_sorted = sorted(rows, key=lambda r: float(r.get("score") or 0), reverse=True)
        out: list[str] = []
        for r in rows_sorted:
            sym = str(r.get("sym") or "").upper()
            if sym and sym not in SURFACE_DENY and sym not in out:
                out.append(sym)
        return out
    except Exception as exc:  # AM6: surface scan_candidate_symbols failures instead of silent []
        import logging

        logging.getLogger(__name__).warning("scan_candidate_symbols failed: %s", exc)
        return []
    finally:
        gs.close()


def resolve_watchlist() -> list[str]:
    """Heat = optional env WATCHLIST seats + same-day scan/movers(≤8). SURFACE_DENY veto only."""
    import heat_nomination

    return list(heat_nomination.resolve_heat().get("watchlist") or [])


def resolve_heat_meta() -> dict:
    """Full heat pack: watchlist + sources + scan_candidates overflow."""
    import heat_nomination

    return heat_nomination.resolve_heat()


def bfs_candidate_symbols() -> list[str]:
    """Alias — 最近一次扫描候选(兼容旧调用)."""
    return scan_candidate_symbols()


def alpaca_ticker(canonical: str) -> str:
    return ALPACA_SYMBOL.get(canonical, canonical)


def canonical_ticker(alpaca_sym: str, requested: list[str]) -> str:
    for c in requested:
        if alpaca_ticker(c) == alpaca_sym:
            return c
    return alpaca_sym


def _bfs_window_ts_bounds(date_str: str, window: str) -> tuple[float, float]:
    """ET scan windows: AM ~09:40, PM ~15:30 (grace through next hour)."""
    day = dt.date.fromisoformat(date_str)
    if window == "AM":
        start = dt.datetime.combine(day, dt.time(9, 35), tzinfo=_ET)
        end = dt.datetime.combine(day, dt.time(12, 5), tzinfo=_ET)
    else:
        start = dt.datetime.combine(day, dt.time(15, 25), tzinfo=_ET)
        end = dt.datetime.combine(day, dt.time(16, 30), tzinfo=_ET)
    return start.timestamp(), end.timestamp()


def latest_bfs(gs: sqlite3.Connection, date_str: str, window: str) -> dict | None:
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
            "AND ts>=? AND ts<? "
            "ORDER BY id DESC LIMIT 1",
            (ts_lo, ts_hi),
        ).fetchone()
    if not row:
        return None
    payload = json.loads(row[1])
    payload["_event_id"] = row[0]
    payload.setdefault("date", date_str)
    payload.setdefault("window", window)
    return payload


# ---- Phase 0.5: 任务与进度事件(仪式感绑真实事件的存储层) ----
JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, kind TEXT, created INTEGER, status TEXT, pct REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS job_events(
  id INTEGER PRIMARY KEY, job_id INTEGER, ts INTEGER, pct REAL, kind TEXT, payload TEXT);
"""


def conn_jobs() -> sqlite3.Connection:
    c = conn()
    c.executescript(JOBS_SCHEMA)
    return c


def job_event(c: sqlite3.Connection, job_id: int, pct: float, kind: str, payload: dict) -> None:
    c.execute(
        "INSERT INTO job_events(job_id, ts, pct, kind, payload) VALUES(?,?,?,?,?)",
        (job_id, int(time.time()), pct, kind, json.dumps(payload, ensure_ascii=False)),
    )
    c.execute(
        "UPDATE jobs SET pct=?, status=CASE WHEN ?>=100 THEN 'done' ELSE 'running' END WHERE id=?",
        (pct, pct, job_id),
    )


# ---- Alpha Factory (GRID V1.1) ----
FACTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS factor_drafts(
  id INTEGER PRIMARY KEY,
  created INTEGER NOT NULL,
  slug TEXT,
  name TEXT,
  hypothesis TEXT,
  code TEXT,
  status TEXT NOT NULL,
  route TEXT,
  trace_id TEXT,
  test INTEGER DEFAULT 0,
  meta TEXT);
CREATE TABLE IF NOT EXISTS factor_reviews(
  id INTEGER PRIMARY KEY,
  draft_id INTEGER NOT NULL,
  job_id INTEGER,
  created INTEGER NOT NULL,
  status TEXT NOT NULL,
  metrics TEXT,
  grid_explain TEXT,
  error TEXT);
CREATE TABLE IF NOT EXISTS factor_proposals(
  id INTEGER PRIMARY KEY,
  draft_id INTEGER NOT NULL,
  review_id INTEGER NOT NULL,
  created INTEGER NOT NULL,
  status TEXT NOT NULL,
  decision_ts INTEGER,
  meta TEXT);
CREATE INDEX IF NOT EXISTS ix_factor_drafts_status ON factor_drafts(status);
CREATE INDEX IF NOT EXISTS ix_factor_proposals_status ON factor_proposals(status);
"""


def conn_factory() -> sqlite3.Connection:
    c = conn()
    c.executescript(FACTORY_SCHEMA)
    ensure_factor_drafts_guard(c)
    return c


def _is_bar_shaped_draft_row(
    code: str | None,
    status: str | float | int | None,
    name: str | float | int | None,
) -> bool:
    if code and "def factor" in str(code):
        return False
    if isinstance(status, (int, float)) or isinstance(name, (int, float)):
        return True
    return not (code and "def factor" in code)


def ensure_factor_drafts_guard(c: sqlite3.Connection) -> None:
    """T2.3: schema guard — bar-shaped rows cannot insert into factor_drafts."""
    row = c.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='factor_drafts'"
    ).fetchone()
    if row and row[0] and "def factor" in (row[0] or ""):
        return
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS factor_drafts_guarded(
          id INTEGER PRIMARY KEY,
          created INTEGER NOT NULL,
          slug TEXT,
          name TEXT NOT NULL,
          hypothesis TEXT,
          code TEXT NOT NULL CHECK (code LIKE '%def factor%'),
          status TEXT NOT NULL CHECK (typeof(status)='text'),
          route TEXT,
          trace_id TEXT,
          test INTEGER DEFAULT 0,
          meta TEXT);
        INSERT OR IGNORE INTO factor_drafts_guarded
          SELECT id, created, slug,
                 COALESCE(CAST(name AS TEXT), 'unknown'),
                 hypothesis, COALESCE(code, ''),
                 COALESCE(CAST(status AS TEXT), 'draft'),
                 route, trace_id, test, meta
          FROM factor_drafts
          WHERE code LIKE '%def factor%' AND typeof(status)='text' AND typeof(name)='text';
        DROP TABLE IF EXISTS factor_drafts;
        ALTER TABLE factor_drafts_guarded RENAME TO factor_drafts;
        CREATE INDEX IF NOT EXISTS ix_factor_drafts_status ON factor_drafts(status);
        """
    )


def slugify(name: str) -> str:
    s = "".join(ch if ch.isalnum() else "_" for ch in (name or "factor").lower())
    return (s.strip("_") or "factor")[:48]


def options_active_universe(c: sqlite3.Connection, watchlist: list[str], *,
                            oi_floor: float | None = None) -> list[str]:
    """断层热力 universe 滤:仅保留当日有 Theta options 因子(net_gex/total_oi)且 chain OI ≥ 地板的标的。

    无 Theta 数据的标的跳过(断层位无法定版)。oi_floor 默认 FAULTLINE_OI_FLOOR_PCT × 全链 OI,
    此处简化:只要有 total_oi 因子即视为 options-active(地板判定在 fault_lines F2 已做)。
    """
    if not watchlist:
        return []
    out: list[str] = []
    for sym in watchlist:
        row = c.execute(
            "SELECT 1 FROM factors WHERE symbol=? AND name IN ('net_gex','total_oi') LIMIT 1", (sym,)
        ).fetchone()
        if row:
            out.append(sym)
    return out
