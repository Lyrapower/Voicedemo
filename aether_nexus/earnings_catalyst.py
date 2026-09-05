"""Dual-source earnings date verification for sonnet-earnings lane."""
from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

try:
    import yfinance as yf
except ImportError:
    yf = None

_ET = ZoneInfo("America/New_York")  # trading-date logic uses ET (DST-aware)


def _parse_date(val: Any) -> dt.date | None:
    if val is None:
        return None
    if hasattr(val, "date"):
        return val.date()
    if isinstance(val, str) and len(val) >= 10:
        try:
            return dt.date.fromisoformat(val[:10])
        except ValueError:
            return None
    return None


def _source_yfinance_calendar(symbol: str) -> dt.date | None:
    if yf is None:
        return None
    try:
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        today = dt.datetime.now(_ET).date()
        dates: list[Any] = []
        if cal is None:
            return None
        if hasattr(cal, "empty") and cal.empty:
            return None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or []
        elif hasattr(cal, "loc"):
            if "Earnings Date" in getattr(cal, "index", []):
                dates = list(cal.loc["Earnings Date"].tolist())
            elif "Earnings Date" in getattr(cal, "columns", []):
                dates = list(cal["Earnings Date"].tolist())
        if not isinstance(dates, list):
            dates = [dates]
        for x in dates:
            d = _parse_date(x)
            if d and (d - today).days >= 0:
                return d
    except Exception:
        return None
    return None


def _source_yfinance_info(symbol: str) -> dt.date | None:
    if yf is None:
        return None
    try:
        info = yf.Ticker(symbol).info or {}
        for key in ("earningsDate", "nextEarningsDate", "earningsTimestamp"):
            raw = info.get(key)
            if isinstance(raw, (list, tuple)) and raw:
                raw = raw[0]
            d = _parse_date(raw)
            if d and (d - dt.datetime.now(_ET).date()).days >= 0:
                return d
    except Exception:
        return None
    return None


def verify_earnings_date(symbol: str) -> dict[str, Any]:
    """Two independent yfinance surfaces must agree on the next earnings date."""
    sym = symbol.upper()
    s1 = _source_yfinance_calendar(sym)
    s2 = _source_yfinance_info(sym)
    verified = bool(s1 and s2 and s1 == s2)
    chosen = s1 if verified else None
    return {
        "symbol": sym,
        "date": chosen.isoformat() if chosen else None,
        "verified": verified,
        "sources": {
            "calendar": s1.isoformat() if s1 else None,
            "info": s2.isoformat() if s2 else None,
        },
        "unverified_catalyst": bool(s1 or s2) and not verified,
    }


def earnings_in_window(
    symbol: str,
    *,
    min_days: int = 1,
    max_days: int = 2,
    today: dt.date | None = None,
) -> dict[str, Any] | None:
    today = today or dt.datetime.now(_ET).date()
    v = verify_earnings_date(symbol)
    if not v.get("verified") or not v.get("date"):
        return None
    d = dt.date.fromisoformat(v["date"])
    days = (d - today).days
    if min_days <= days <= max_days:
        return {**v, "days_to_earnings": days}
    return None
