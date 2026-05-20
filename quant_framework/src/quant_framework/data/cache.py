"""SQLite-based cache for prices, fundamentals, fetch log, and signal runs."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT,
    date TEXT,
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER, adj_close REAL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT,
    as_of_date TEXT,
    market_cap REAL,
    book_value REAL,
    total_revenue REAL,
    gross_profit REAL,
    total_assets REAL,
    shares_outstanding REAL,
    fetched_at TEXT,
    PRIMARY KEY (ticker, as_of_date)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT,
    fetch_type TEXT,
    fetch_date TEXT,
    success INTEGER,
    error_message TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS signal_runs (
    run_id TEXT PRIMARY KEY,
    as_of_date TEXT,
    completed_at TEXT,
    universe_size INTEGER,
    universe_with_signals INTEGER
);

CREATE TABLE IF NOT EXISTS signal_results (
    run_id TEXT,
    ticker TEXT,
    momentum_12_1_raw REAL,
    momentum_12_1_zscore REAL,
    book_to_market_raw REAL,
    book_to_market_zscore REAL,
    gross_profitability_raw REAL,
    gross_profitability_zscore REAL,
    low_vol_12m_raw REAL,
    low_vol_12m_zscore REAL,
    combined_score REAL,
    rank INTEGER,
    PRIMARY KEY (run_id, ticker)
);
"""


class DataCache:
    def __init__(self, db_path: Path, fundamentals_cache_days: int = 30) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.fundamentals_cache_days = fundamentals_cache_days
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # --- Prices ---

    def get_cached_prices(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        if not tickers:
            return pd.DataFrame()
        placeholders = ",".join("?" * len(tickers))
        query = f"""
            SELECT ticker, date, open, high, low, close, volume, adj_close
            FROM prices
            WHERE ticker IN ({placeholders})
              AND date >= ? AND date <= ?
        """
        params: list[Any] = list(tickers) + [
            start_date.isoformat(),
            end_date.isoformat(),
        ]
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.set_index(["date", "ticker"]).sort_index()
        return df

    def prices_fully_cached(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        as_of_today: date | None = None,
    ) -> bool:
        """Prices expire same-day: cache valid only if we have rows for all tickers in range."""
        if not tickers:
            return True
        cached = self.get_cached_prices(tickers, start_date, end_date)
        if cached.empty:
            return False
        today = as_of_today or date.today()
        # Same-day expire: require fetch_log success today for each ticker
        with self._connect() as conn:
            for ticker in tickers:
                row = conn.execute(
                    """
                    SELECT 1 FROM fetch_log
                    WHERE ticker = ? AND fetch_type = 'prices'
                      AND fetch_date = ? AND success = 1
                      AND date(created_at) = date('now', 'localtime')
                    LIMIT 1
                    """,
                    (ticker, end_date.isoformat()),
                ).fetchone()
                if row is None:
                    return False
        return True

    def store_prices(self, df: pd.DataFrame) -> None:
        if df.empty:
            return
        records = []
        reset = df.reset_index()
        for _, row in reset.iterrows():
            d = row["date"]
            if hasattr(d, "date"):
                d = d.date() if hasattr(d, "date") and callable(getattr(d, "date", None)) else d
            if isinstance(d, pd.Timestamp):
                d = d.date()
            records.append(
                (
                    str(row["ticker"]),
                    d.isoformat() if isinstance(d, date) else str(d)[:10],
                    float(row.get("open", 0) or 0),
                    float(row.get("high", 0) or 0),
                    float(row.get("low", 0) or 0),
                    float(row.get("close", 0) or 0),
                    int(row.get("volume", 0) or 0),
                    float(row.get("adj_close", 0) or 0),
                )
            )
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO prices
                (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()

    # --- Fundamentals ---

    def get_cached_fundamentals(
        self,
        tickers: list[str],
        as_of_date: date,
    ) -> pd.DataFrame:
        if not tickers:
            return pd.DataFrame()
        placeholders = ",".join("?" * len(tickers))
        cutoff = (datetime.utcnow() - timedelta(days=self.fundamentals_cache_days)).isoformat()
        query = f"""
            SELECT ticker, market_cap, book_value, total_revenue, gross_profit,
                   total_assets, shares_outstanding
            FROM fundamentals
            WHERE ticker IN ({placeholders})
              AND as_of_date = ?
              AND fetched_at >= ?
        """
        params: list[Any] = list(tickers) + [as_of_date.isoformat(), cutoff]
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        return df.set_index("ticker")

    def store_fundamentals(self, df: pd.DataFrame, as_of_date: date) -> None:
        if df.empty:
            return
        now = datetime.utcnow().isoformat()
        records = []
        for ticker, row in df.iterrows():
            records.append(
                (
                    str(ticker),
                    as_of_date.isoformat(),
                    _f(row.get("market_cap")),
                    _f(row.get("book_value")),
                    _f(row.get("total_revenue")),
                    _f(row.get("gross_profit")),
                    _f(row.get("total_assets")),
                    _f(row.get("shares_outstanding")),
                    now,
                )
            )
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO fundamentals
                (ticker, as_of_date, market_cap, book_value, total_revenue,
                 gross_profit, total_assets, shares_outstanding, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()

    # --- Fetch log ---

    def log_fetch(
        self,
        ticker: str,
        fetch_type: str,
        fetch_date: date,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fetch_log (ticker, fetch_type, fetch_date, success, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    fetch_type,
                    fetch_date.isoformat(),
                    1 if success else 0,
                    error_message,
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def last_fetch_time(self) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(created_at) AS t FROM fetch_log WHERE success = 1"
            ).fetchone()
        return row["t"] if row and row["t"] else None

    def fetch_log_summary_24h(self) -> dict[str, int]:
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT success, COUNT(*) AS c FROM fetch_log
                WHERE created_at >= ?
                GROUP BY success
                """,
                (cutoff,),
            ).fetchall()
        out = {"success": 0, "failure": 0}
        for r in rows:
            key = "success" if r["success"] else "failure"
            out[key] = r["c"]
        return out

    def db_size_bytes(self) -> int:
        if self.db_path.exists():
            return self.db_path.stat().st_size
        return 0

    # --- Signal runs ---

    def save_signal_run(
        self,
        run_id: str,
        as_of_date: date,
        universe_size: int,
        universe_with_signals: int,
        results: pd.DataFrame,
    ) -> None:
        completed = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signal_runs (run_id, as_of_date, completed_at, universe_size, universe_with_signals)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    as_of_date.isoformat(),
                    completed,
                    universe_size,
                    universe_with_signals,
                ),
            )
            records = []
            for ticker, row in results.iterrows():
                records.append(
                    (
                        run_id,
                        str(ticker),
                        _f(row.get("momentum_12_1_raw")),
                        _f(row.get("momentum_12_1_zscore")),
                        _f(row.get("book_to_market_raw")),
                        _f(row.get("book_to_market_zscore")),
                        _f(row.get("gross_profitability_raw")),
                        _f(row.get("gross_profitability_zscore")),
                        _f(row.get("low_vol_12m_raw")),
                        _f(row.get("low_vol_12m_zscore")),
                        _f(row.get("combined_score")),
                        int(row["rank"]) if pd.notna(row.get("rank")) else None,
                    )
                )
            conn.executemany(
                """
                INSERT OR REPLACE INTO signal_results
                (run_id, ticker, momentum_12_1_raw, momentum_12_1_zscore,
                 book_to_market_raw, book_to_market_zscore,
                 gross_profitability_raw, gross_profitability_zscore,
                 low_vol_12m_raw, low_vol_12m_zscore, combined_score, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()

    def list_signal_runs(self, limit: int = 50) -> pd.DataFrame:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, as_of_date, completed_at, universe_size, universe_with_signals
                FROM signal_runs ORDER BY completed_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    def get_signal_results(self, run_id: str) -> pd.DataFrame:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM signal_results WHERE run_id = ? ORDER BY rank ASC",
                (run_id,),
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        if "ticker" in df.columns:
            df = df.set_index("ticker")
        return df

    def get_last_signal_run(self) -> dict | None:
        runs = self.list_signal_runs(limit=1)
        if runs.empty:
            return None
        return runs.iloc[0].to_dict()

    @staticmethod
    def new_run_id() -> str:
        return str(uuid.uuid4())


def _f(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
