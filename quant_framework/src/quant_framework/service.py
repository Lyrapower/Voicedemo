"""Shared service wiring for CLI, dashboard, and bot."""

from __future__ import annotations

from quant_framework.config import get_settings
from quant_framework.data.cache import DataCache
from quant_framework.data.yfinance_adapter import YFinanceAdapter
from quant_framework.signals.combiner import SignalCombiner
from quant_framework.signals.low_vol import LowVolSignal
from quant_framework.signals.momentum import MomentumSignal
from quant_framework.signals.quality import QualitySignal
from quant_framework.signals.value import ValueSignal


def build_cache() -> DataCache:
    s = get_settings()
    return DataCache(s.cache_path, fundamentals_cache_days=s.fundamentals_cache_days)


def build_adapter() -> YFinanceAdapter:
    return YFinanceAdapter(build_cache())


def build_combiner(weights: list[float] | None = None) -> SignalCombiner:
    cache = build_cache()
    combiner = SignalCombiner(
        signals=[
            MomentumSignal(),
            ValueSignal(),
            QualitySignal(),
            LowVolSignal(),
        ],
        weights=weights,
        cache=cache,
    )
    return combiner


def most_recent_month_end() -> "date":
    from datetime import date

    today = date.today()
    if today.month == 1:
        return date(today.year - 1, 12, 31)
    first = date(today.year, today.month, 1)
    from datetime import timedelta

    return first - timedelta(days=1)
