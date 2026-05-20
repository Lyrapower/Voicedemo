"""Signal abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from quant_framework.data.adapter import DataAdapter


class Signal(ABC):
    name: str

    @abstractmethod
    def compute(
        self,
        universe: list[str],
        as_of_date: date,
        data_adapter: DataAdapter,
    ) -> pd.Series:
        """
        Returns Series indexed by ticker with raw signal values.
        Higher = more attractive (long signal).
        NaN where signal cannot be computed.
        """
        pass
