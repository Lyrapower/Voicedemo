"""
12-1 month momentum signal (Jegadeesh & Titman, 1993).

Methodology:
    Return from t-12 months to t-1 month using adj_close, skipping the most
    recent month to reduce short-term reversal contamination.

Reference:
    Jegadeesh, N., & Titman, S. (1993). Returns to buying winners and selling
    losers: Implications for stock market efficiency. Journal of Finance, 48(1).

Direction:
    Higher momentum → more attractive (long).

Limitations:
    Requires ~13 months of price history; delisted or thinly traded names may
    lack sufficient data.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from quant_framework.data.adapter import DataAdapter
from quant_framework.signals.base import Signal


class MomentumSignal(Signal):
    name = "momentum_12_1"

    def compute(
        self,
        universe: list[str],
        as_of_date: date,
        data_adapter: DataAdapter,
    ) -> pd.Series:
        start = as_of_date - timedelta(days=400)
        prices = data_adapter.get_prices(universe, start, as_of_date)
        if prices.empty:
            return pd.Series(dtype=float, index=universe)

        adj = prices["adj_close"].unstack("ticker")
        results: dict[str, float] = {}
        for ticker in universe:
            if ticker not in adj.columns:
                results[ticker] = np.nan
                continue
            series = adj[ticker].dropna()
            series = series[series.index <= as_of_date]
            if len(series) < 2:
                results[ticker] = np.nan
                continue
            series = series.sort_index()
            # t-1 month end: last trading day in month before as_of month
            end_cutoff = _month_end_before(as_of_date, months_back=1)
            start_cutoff = _month_end_before(as_of_date, months_back=12)
            end_px = _price_on_or_before(series, end_cutoff)
            start_px = _price_on_or_before(series, start_cutoff)
            if end_px is None or start_px is None or start_px <= 0:
                results[ticker] = np.nan
            else:
                results[ticker] = (end_px / start_px) - 1.0
        return pd.Series(results)


def _month_end_before(d: date, months_back: int) -> date:
    y, m = d.year, d.month
    m -= months_back
    while m <= 0:
        m += 12
        y -= 1
    # last day of that month
    if m == 12:
        next_m = date(y + 1, 1, 1)
    else:
        next_m = date(y, m + 1, 1)
    return next_m - timedelta(days=1)


def _price_on_or_before(series: pd.Series, target: date) -> float | None:
    eligible = series[series.index <= target]
    if eligible.empty:
        return None
    return float(eligible.iloc[-1])
