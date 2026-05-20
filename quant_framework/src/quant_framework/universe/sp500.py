"""S&P 500 universe — hardcoded constituents for v0.1."""

from __future__ import annotations

from datetime import date
from pathlib import Path

_TICKERS_FILE = Path(__file__).parent / "sp500_tickers.txt"


def get_sp500_constituents(as_of_date: date) -> list[str]:
    """
    Returns list of S&P 500 tickers as of given date.

    v0.1: returns current S&P 500 constituents regardless of as_of_date.
    """
    _ = as_of_date
    if not _TICKERS_FILE.exists():
        raise FileNotFoundError(f"Missing ticker list: {_TICKERS_FILE}")
    lines = _TICKERS_FILE.read_text().strip().splitlines()
    tickers = []
    for t in lines:
        t = t.strip().upper()
        if not t:
            continue
        # yfinance uses hyphen for share classes (e.g. BRK-B)
        tickers.append(t.replace(".", "-"))
    return tickers
