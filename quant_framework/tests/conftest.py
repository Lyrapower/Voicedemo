"""Pytest fixtures — no external API calls."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_framework.data.adapter import DataAdapter
from quant_framework.data.cache import DataCache

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = date(2024, 6, 28)
TICKERS = ["AAA", "BBB", "CCC"]


class MockDataAdapter(DataAdapter):
    def __init__(self, prices: pd.DataFrame, fundamentals: pd.DataFrame) -> None:
        self._prices = prices
        self._fundamentals = fundamentals

    def get_prices(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        df = self._prices
        mask = (
            df.index.get_level_values("ticker").isin(tickers)
            & (df.index.get_level_values("date") >= start_date)
            & (df.index.get_level_values("date") <= end_date)
        )
        return df.loc[mask].copy()

    def get_fundamentals(
        self,
        tickers: list[str],
        as_of_date: date,
    ) -> pd.DataFrame:
        return self._fundamentals.reindex(tickers)


def _build_mock_prices() -> pd.DataFrame:
    rows = []
    start = AS_OF - timedelta(days=400)
    d = start
    rng = np.random.default_rng(42)
    base = {"AAA": 100.0, "BBB": 50.0, "CCC": 200.0}
    while d <= AS_OF:
        for t in TICKERS:
            if d == start:
                px = base[t]
            else:
                px = rows[-1][6] * (1 + rng.normal(0.0005, 0.01)) if rows and rows[-1][1] == t else base[t]
            if not rows or rows[-1][1] != t:
                px = base[t] * (1 + rng.normal(0, 0.02))
            adj = px
            rows.append((d, t, px, px, px, px, 1_000_000, adj))
        d += timedelta(days=1)
    # Simpler: deterministic growth
    rows = []
    d = start
    prices = {t: base[t] for t in TICKERS}
    while d <= AS_OF:
        for t in TICKERS:
            prices[t] *= 1.0003 + (0.0001 if t == "AAA" else -0.0001 if t == "BBB" else 0)
            p = prices[t]
            rows.append((d, t, p, p, p, p, 1000, p))
        d += timedelta(days=1)
    df = pd.DataFrame(
        rows,
        columns=["date", "ticker", "open", "high", "low", "close", "volume", "adj_close"],
    )
    return df.set_index(["date", "ticker"])


def _build_mock_fundamentals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "market_cap": [1e10, 5e9, 2e10],
            "book_value": [5e9, 3e9, 8e9],
            "total_revenue": [2e9, 1e9, 5e9],
            "gross_profit": [8e8, 4e8, 2e9],
            "total_assets": [6e9, 4e9, 10e9],
            "shares_outstanding": [1e8, 5e7, 2e8],
        },
        index=TICKERS,
    )


@pytest.fixture
def mock_prices() -> pd.DataFrame:
    path = FIXTURES / "prices.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        df.index = pd.MultiIndex.from_arrays(
            [pd.to_datetime(df["date"]).dt.date, df["ticker"]],
            names=["date", "ticker"],
        )
        return df.drop(columns=["date", "ticker"], errors="ignore")
    df = _build_mock_prices()
    out = df.reset_index()
    out.to_parquet(path, index=False)
    return df


@pytest.fixture
def mock_fundamentals() -> pd.DataFrame:
    path = FIXTURES / "fundamentals.parquet"
    if path.exists():
        return pd.read_parquet(path).set_index("ticker")
    df = _build_mock_fundamentals()
    df.reset_index(names="ticker").to_parquet(path, index=False)
    return df


@pytest.fixture
def mock_adapter(mock_prices, mock_fundamentals) -> MockDataAdapter:
    return MockDataAdapter(mock_prices, mock_fundamentals)


@pytest.fixture
def temp_cache(tmp_path) -> DataCache:
    return DataCache(tmp_path / "test.db")
