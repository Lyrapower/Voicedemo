"""
Low volatility signal — inverted 12-month annualized volatility.

Methodology:
    Daily returns from adj_close over ~252 trading days; annualized std dev;
    signal = -volatility so higher values mean lower vol (more attractive).

Reference:
    Ang, Hodrick, Xing & Zhang (2006); Baker, Bradley & Wurgler (2011) on low-vol anomaly.

Direction:
    Higher signal → lower realized vol → more attractive.

Limitations:
    Requires sufficient daily history; crisis periods inflate vol estimates.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from quant_framework.data.adapter import DataAdapter
from quant_framework.signals.base import Signal

TRADING_DAYS = 252


class LowVolSignal(Signal):
    name = "low_vol_12m"

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
            series = series[series.index <= as_of_date].sort_index()
            if len(series) < 20:
                results[ticker] = np.nan
                continue
            rets = series.pct_change().dropna()
            rets = rets.tail(TRADING_DAYS)
            if len(rets) < 10:
                results[ticker] = np.nan
            else:
                vol = float(rets.std() * np.sqrt(TRADING_DAYS))
                results[ticker] = -vol
        return pd.Series(results)
