"""Factor combination, cross-sectional z-scores, ranking, and persistence."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quant_framework.data.adapter import DataAdapter
from quant_framework.data.cache import DataCache
from quant_framework.signals.base import Signal

# Column name mapping for DB persistence
_SIGNAL_DB_MAP = {
    "momentum_12_1": ("momentum_12_1_raw", "momentum_12_1_zscore"),
    "book_to_market": ("book_to_market_raw", "book_to_market_zscore"),
    "gross_profitability": ("gross_profitability_raw", "gross_profitability_zscore"),
    "low_vol_12m": ("low_vol_12m_raw", "low_vol_12m_zscore"),
}


class SignalCombiner:
    def __init__(
        self,
        signals: list[Signal],
        weights: list[float] | None = None,
        cache: DataCache | None = None,
    ) -> None:
        self.signals = signals
        if weights is None:
            weights = [1.0 / len(signals)] * len(signals)
        if len(weights) != len(signals):
            raise ValueError("weights length must match signals length")
        total = sum(weights)
        self.weights = [w / total for w in weights]
        self.cache = cache

    def compute_combined(
        self,
        universe: list[str],
        as_of_date: date,
        data_adapter: DataAdapter,
    ) -> pd.DataFrame:
        raw_cols: dict[str, pd.Series] = {}
        for sig, w in zip(self.signals, self.weights):
            raw = sig.compute(universe, as_of_date, data_adapter)
            raw_cols[sig.name] = raw

        df = pd.DataFrame(raw_cols)
        z_cols: dict[str, pd.Series] = {}
        for name in raw_cols:
            z = _cross_sectional_zscore(df[name])
            z_cols[f"{name}_zscore"] = z
            df[f"{name}_raw"] = df[name]
            df[f"{name}_zscore"] = z
            df = df.drop(columns=[name])

        # Exclude tickers with ANY NaN in z-scores
        zscore_only = df[[c for c in df.columns if c.endswith("_zscore")]]
        valid = zscore_only.dropna(how="any").index

        combined = pd.Series(0.0, index=df.index, dtype=float)
        for sig, w in zip(self.signals, self.weights):
            col = f"{sig.name}_zscore"
            combined = combined + df[col].fillna(0) * w
        combined.loc[~df.index.isin(valid)] = np.nan

        df["combined_score"] = combined
        ranked = df["combined_score"].dropna().sort_values(ascending=False)
        rank_map = {t: i + 1 for i, t in enumerate(ranked.index)}
        df["rank"] = df.index.map(rank_map)

        # Reorder columns for output
        ordered = []
        for sig in self.signals:
            raw_c, z_c = _SIGNAL_DB_MAP.get(sig.name, (f"{sig.name}_raw", f"{sig.name}_zscore"))
            if f"{sig.name}_raw" in df.columns:
                ordered.extend([f"{sig.name}_raw", f"{sig.name}_zscore"])
            else:
                ordered.extend([raw_c, z_c])
        ordered = list(dict.fromkeys(ordered + ["combined_score", "rank"]))
        out = df[[c for c in ordered if c in df.columns]]

        if self.cache is not None:
            run_id = DataCache.new_run_id()
            db_df = _to_db_columns(out)
            self.cache.save_signal_run(
                run_id=run_id,
                as_of_date=as_of_date,
                universe_size=len(universe),
                universe_with_signals=int(out["rank"].notna().sum()),
                results=db_df,
            )
            out.attrs["run_id"] = run_id

        return out


def _cross_sectional_zscore(s: pd.Series) -> pd.Series:
    valid = s.dropna()
    if len(valid) < 2:
        return pd.Series(np.nan, index=s.index)
    mu = valid.mean()
    sigma = valid.std()
    if sigma == 0 or np.isnan(sigma):
        return pd.Series(0.0, index=s.index).where(s.notna(), np.nan)
    return (s - mu) / sigma


def _to_db_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "momentum_12_1_raw": "momentum_12_1_raw",
        "momentum_12_1_zscore": "momentum_12_1_zscore",
        "book_to_market_raw": "book_to_market_raw",
        "book_to_market_zscore": "book_to_market_zscore",
        "gross_profitability_raw": "gross_profitability_raw",
        "gross_profitability_zscore": "gross_profitability_zscore",
        "low_vol_12m_raw": "low_vol_12m_raw",
        "low_vol_12m_zscore": "low_vol_12m_zscore",
    }
    out = df.rename(columns=rename)
    return out
