"""
Gross profitability quality signal (Novy-Marx, 2013).

Methodology:
    gross_profit / total_assets from latest quarterly financials.

Reference:
    Novy-Marx, R. (2013). The other side of value: The gross profitability premium.

Direction:
    Higher gross profitability → more attractive.

Limitations:
    Missing or zero total_assets → NaN; sector differences not neutralized.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quant_framework.data.adapter import DataAdapter
from quant_framework.signals.base import Signal


class QualitySignal(Signal):
    name = "gross_profitability"

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
            gp = row.get("gross_profit")
            ta = row.get("total_assets")
            if gp is None or ta is None or pd.isna(gp) or pd.isna(ta):
                results[ticker] = np.nan
            elif float(ta) <= 0:
                results[ticker] = np.nan
            else:
                results[ticker] = float(gp) / float(ta)
        return pd.Series(results)
