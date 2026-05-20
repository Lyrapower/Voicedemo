import numpy as np

from quant_framework.signals.low_vol import LowVolSignal
from conftest import AS_OF, TICKERS


def test_low_vol_happy_path(mock_adapter):
    out = LowVolSignal().compute(TICKERS, AS_OF, mock_adapter)
    assert out.notna().all()
    assert (out <= 0).all()


def test_low_vol_insufficient_history(mock_adapter):
    out = LowVolSignal().compute(["UNKNOWN"], AS_OF, mock_adapter)
    assert np.isnan(out.iloc[0])
