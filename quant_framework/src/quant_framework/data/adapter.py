"""Abstract data adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class DataAdapter(ABC):
    @abstractmethod
    def get_prices(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Returns DataFrame with MultiIndex (date, ticker) and columns:
        open, high, low, close, volume, adj_close.
        adj_close adjusts for splits + dividends.
        """
        pass

    @abstractmethod
    def get_fundamentals(
        self,
        tickers: list[str],
        as_of_date: date,
    ) -> pd.DataFrame:
        """
        Returns DataFrame indexed by ticker with columns:
        market_cap, book_value, total_revenue, gross_profit,
        total_assets, shares_outstanding.
        Values reflect most recent quarterly filing as_of_date.
        """
        pass
