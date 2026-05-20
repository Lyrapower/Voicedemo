import numpy as np
import pandas as pd

from quant_framework.signals.value import ValueSignal
from conftest import AS_OF, MockDataAdapter, TICKERS


def test_value_happy_path(mock_adapter):
    sig = ValueSignal()
    out = sig.compute(TICKERS, AS_OF, mock_adapter)
    assert out.notna().all()
    assert (out > 0).all()


def test_value_negative_book(mock_fundamentals, mock_prices):
    fund = mock_fundamentals.copy()
    fund.loc["AAA", "book_value"] = -1.0
    adapter = MockDataAdapter(mock_prices, fund)
    out = ValueSignal().compute(["AAA"], AS_OF, adapter)
    assert np.isnan(out["AAA"])


def test_value_missing_fundamentals(mock_prices, mock_fundamentals):
    adapter = MockDataAdapter(mock_prices, mock_fundamentals.iloc[:0])
    out = ValueSignal().compute(["AAA"], AS_OF, adapter)
    assert np.isnan(out["AAA"])
