import numpy as np

from quant_framework.signals.quality import QualitySignal
from conftest import AS_OF, MockDataAdapter, TICKERS


def test_quality_happy_path(mock_adapter):
    out = QualitySignal().compute(TICKERS, AS_OF, mock_adapter)
    assert out.notna().all()


def test_quality_zero_assets(mock_fundamentals, mock_prices):
    fund = mock_fundamentals.copy()
    fund.loc["BBB", "total_assets"] = 0
    adapter = MockDataAdapter(mock_prices, fund)
    out = QualitySignal().compute(["BBB"], AS_OF, adapter)
    assert np.isnan(out["BBB"])
