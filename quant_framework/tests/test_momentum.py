import numpy as np

from quant_framework.signals.momentum import MomentumSignal
from conftest import AS_OF, TICKERS


def test_momentum_happy_path(mock_adapter):
    sig = MomentumSignal()
    out = sig.compute(TICKERS, AS_OF, mock_adapter)
    assert len(out) == len(TICKERS)
    assert out.notna().any()


def test_momentum_single_ticker(mock_adapter):
    sig = MomentumSignal()
    out = sig.compute(["AAA"], AS_OF, mock_adapter)
    assert len(out) == 1


def test_momentum_missing_data(mock_adapter):
    sig = MomentumSignal()
    out = sig.compute(["UNKNOWN"], AS_OF, mock_adapter)
    assert np.isnan(out.iloc[0])
