"""Exchange calendar helpers — spec §1 (half days: PREMARKET only)."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")  # trading-date logic uses ET (DST-aware)

try:
    from aether_dryrun import is_trading_day
except Exception:

    def is_trading_day(d: dt.date | None = None) -> bool:
        d = d or dt.datetime.now(_ET).date()
        return d.weekday() < 5


def is_half_trading_day(d: dt.date | None = None) -> bool:
    """True when session closes before regular 16:00 ET (Alpaca calendar).

    M: on calendar-API failure / missing headers, return True (conservative — assume
    half-day) so the EXECUTION window is skipped rather than running on an unverified
    early-close day. Previously returned False (treated as full day) → EXECUTION could
    run on a half-close day when the calendar API was down.
    """
    d = d or dt.datetime.now(_ET).date()  # M: ET, not local date.today()
    if not is_trading_day(d):
        return False
    try:
        from aether_dryrun import ALPACA_TRADING_BASE, _alpaca_headers, _request_json
        import logging

        key = d.isoformat()
        headers = _alpaca_headers()
        if not headers:
            logging.getLogger(__name__).warning("is_half_trading_day: no Alpaca headers → conservative True")
            return True
        data = _request_json(
            f"{ALPACA_TRADING_BASE}/v2/calendar",
            headers=headers,
            params={"start": key, "end": key},
            provider="alpaca",
            endpoint="calendar",
        )
        if not isinstance(data, list):
            logging.getLogger(__name__).warning("is_half_trading_day: non-list calendar → conservative True")
            return True
        for entry in data:
            if entry.get("date") != key:
                continue
            close = str(entry.get("close") or "16:00")
            parts = close.split(":")
            if len(parts) < 2:
                return True  # M: unparseable close → conservative
            close_m = int(parts[0]) * 60 + int(parts[1])
            return close_m < 16 * 60
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("is_half_trading_day: calendar lookup failed → conservative True: %s", exc)
        return True  # M: conservative — skip EXECUTION when unsure
    return False
