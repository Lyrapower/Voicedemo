from datetime import date

import pandas as pd

from quant_framework.data.cache import DataCache


def test_cache_prices_roundtrip(temp_cache):
    rows = [
        ("AAPL", "2024-01-02", 1.0, 2.0, 0.5, 1.5, 1000, 1.5),
        ("AAPL", "2024-01-03", 1.1, 2.1, 0.6, 1.6, 1100, 1.6),
    ]
    df = pd.DataFrame(
        rows,
        columns=["ticker", "date", "open", "high", "low", "close", "volume", "adj_close"],
    )
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.set_index(["date", "ticker"])
    temp_cache.store_prices(df)
    out = temp_cache.get_cached_prices(["AAPL"], date(2024, 1, 1), date(2024, 1, 10))
    assert len(out) == 2
    assert "adj_close" in out.columns


def test_signal_run_persistence(temp_cache):
    results = pd.DataFrame(
        {
            "momentum_12_1_raw": [0.1],
            "momentum_12_1_zscore": [1.0],
            "book_to_market_raw": [0.5],
            "book_to_market_zscore": [0.5],
            "gross_profitability_raw": [0.2],
            "gross_profitability_zscore": [0.2],
            "low_vol_12m_raw": [-0.15],
            "low_vol_12m_zscore": [0.3],
            "combined_score": [2.0],
            "rank": [1],
        },
        index=["AAPL"],
    )
    temp_cache.save_signal_run("run-1", date(2024, 6, 30), 500, 1, results)
    runs = temp_cache.list_signal_runs()
    assert len(runs) == 1
    loaded = temp_cache.get_signal_results("run-1")
    assert loaded.loc["AAPL", "rank"] == 1


def test_fetch_log(temp_cache):
    temp_cache.log_fetch("MSFT", "prices", date.today(), True)
    temp_cache.log_fetch("MSFT", "prices", date.today(), False, "timeout")
    summary = temp_cache.fetch_log_summary_24h()
    assert summary["success"] >= 1
    assert summary["failure"] >= 1
