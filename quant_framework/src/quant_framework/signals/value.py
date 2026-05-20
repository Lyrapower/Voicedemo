"""
Book-to-market value signal (Fama & French, 1992).

Methodology:
    book_value / market_cap from most recent quarterly fundamentals.

Reference:
    Fama, E. F., & French, K. R. (1992). The cross-section of expected stock returns.

Direction:
    Higher book-to-market → more attractive (value tilt).

Limitations:
    Negative book equity → NaN; yfinance fundamental timing may not match
    point-in-time filings for historical as_of_date.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quant_framework.data.adapter import DataAdapter
from quant_framework.signals.base import Signal


class ValueSignal(Signal):
    name = "book_to_market"

    def compute(
        self,
        universe: list[str],
        as_of_date: date,
        data_adapter: DataAdapter,
    ) -> pd.Series:
        fund = data_adapter.get_fundamentals(universe, as_of_date)
        results: dict[str, float] = {}
        for ticker in universe:
            if ticker not in fund.index:
                results[ticker] = np.nan
                continue
            row = fund.loc[ticker]
            bv = row.get("book_value")
            mc = row.get("market_cap")
            if bv is None or mc is None or pd.isna(bv) or pd.isna(mc):
                results[ticker] = np.nan
            elif float(bv) <= 0 or float(mc) <= 0:
                results[ticker] = np.nan
            else:
                results[ticker] = float(bv) / float(mc)
        return pd.Series(results)
