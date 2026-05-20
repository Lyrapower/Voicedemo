from datetime import date

from quant_framework.universe.sp500 import get_sp500_constituents


def test_sp500_count():
    tickers = get_sp500_constituents(date(2020, 1, 1))
    assert len(tickers) >= 500


def test_sp500_ignores_date():
    t1 = get_sp500_constituents(date(2010, 1, 1))
    t2 = get_sp500_constituents(date(2026, 1, 1))
    assert t1 == t2
