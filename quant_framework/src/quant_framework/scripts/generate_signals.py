#!/usr/bin/env python
"""CLI entry point for signal generation."""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime

import click

from quant_framework.config import get_settings
from quant_framework.data.cache import DataCache
from quant_framework.data.yfinance_adapter import YFinanceAdapter
from quant_framework.signals.combiner import SignalCombiner
from quant_framework.signals.low_vol import LowVolSignal
from quant_framework.signals.momentum import MomentumSignal
from quant_framework.signals.quality import QualitySignal
from quant_framework.signals.value import ValueSignal
from quant_framework.universe.sp500 import get_sp500_constituents


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _default_signals() -> SignalCombiner:
    return SignalCombiner(
        signals=[
            MomentumSignal(),
            ValueSignal(),
            QualitySignal(),
            LowVolSignal(),
        ],
    )


@click.command()
@click.option("--as-of-date", required=True, type=str, help="Signal date YYYY-MM-DD")
@click.option("--output", required=True, type=click.Path(), help="Output CSV path")
def main(as_of_date: str, output: str) -> None:
    """Generate ranked factor signals for the S&P 500 universe."""
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    as_of = _parse_date(as_of_date)
    universe = get_sp500_constituents(as_of)
    cache = DataCache(
        settings.cache_path,
        fundamentals_cache_days=settings.fundamentals_cache_days,
    )
    adapter = YFinanceAdapter(cache)
    combiner = _default_signals()
    combiner.cache = cache

    click.echo(f"Computing signals for {len(universe)} tickers as of {as_of}...")
    results = combiner.compute_combined(universe, as_of, adapter)
    run_id = results.attrs.get("run_id")
    results = results.reset_index(names="ticker")
    results.to_csv(output, index=False)
    click.echo(f"Wrote {len(results)} rows to {output}")
    if run_id:
        click.echo(f"Run ID: {run_id}")
    ranked = results[results["rank"].notna()] if "rank" in results.columns else results
    click.echo(f"Tickers with combined rank: {len(ranked)}")


if __name__ == "__main__":
    main()
