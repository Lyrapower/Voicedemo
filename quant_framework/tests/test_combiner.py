import numpy as np

from quant_framework.signals.combiner import SignalCombiner
from quant_framework.signals.low_vol import LowVolSignal
from quant_framework.signals.momentum import MomentumSignal
from quant_framework.signals.quality import QualitySignal
from quant_framework.signals.value import ValueSignal
from conftest import AS_OF, TICKERS


def test_combiner_happy_path(mock_adapter, temp_cache):
    combiner = SignalCombiner(
        signals=[MomentumSignal(), ValueSignal(), QualitySignal(), LowVolSignal()],
        cache=temp_cache,
    )
    df = combiner.compute_combined(TICKERS, AS_OF, mock_adapter)
    assert "combined_score" in df.columns
    assert "rank" in df.columns
    ranked = df["rank"].dropna()
    assert len(ranked) >= 1
    assert "run_id" in df.attrs


def test_combiner_nan_exclusion(mock_fundamentals, mock_prices, temp_cache):
    from conftest import MockDataAdapter

    fund = mock_fundamentals.copy()
    fund.loc["CCC", "gross_profit"] = np.nan
    adapter = MockDataAdapter(mock_prices, fund)
    combiner = SignalCombiner(
        signals=[MomentumSignal(), ValueSignal(), QualitySignal(), LowVolSignal()],
        cache=temp_cache,
    )
    df = combiner.compute_combined(TICKERS, AS_OF, adapter)
    assert np.isnan(df.loc["CCC", "rank"])


def test_combiner_weights():
    with __import__("pytest").raises(ValueError):
        SignalCombiner(
            signals=[MomentumSignal(), ValueSignal()],
            weights=[1.0],
        )
