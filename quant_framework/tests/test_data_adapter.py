from datetime import date

import pytest

from conftest import AS_OF, TICKERS, MockDataAdapter


def test_mock_adapter_prices(mock_adapter):
    df = mock_adapter.get_prices(TICKERS, date(2023, 1, 1), AS_OF)
    assert not df.empty
    assert set(df.columns) >= {"open", "high", "low", "close", "volume", "adj_close"}
    assert df.index.names == ["date", "ticker"]


def test_mock_adapter_fundamentals(mock_adapter):
    df = mock_adapter.get_fundamentals(TICKERS, AS_OF)
    assert len(df) == len(TICKERS)
    assert "market_cap" in df.columns


def test_mock_adapter_missing_ticker(mock_adapter):
    df = mock_adapter.get_prices(["ZZZZ"], date(2023, 1, 1), AS_OF)
    assert df.empty
