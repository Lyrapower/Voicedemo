"""US equity RTH session: ET clock + NYSE holiday calendar (no live quote)."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
RTH_OPEN = dt.time(9, 30)
RTH_CLOSE = dt.time(16, 0)

# NYSE full-day closures 2025–2027 (observed dates). Early-close days still count as session-open until 16:00 unless added here.
NYSE_HOLIDAYS = frozenset(
    dt.date.fromisoformat(x)
    for x in (
        "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
        "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
        "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    )
)


def is_trading_day(d: dt.date | None = None) -> bool:
    d = d or dt.datetime.now(ET).date()
    if d.weekday() >= 5:
        return False
    return d not in NYSE_HOLIDAYS


def is_rth(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)
    if not is_trading_day(now.date()):
        return False
    return RTH_OPEN <= now.time() < RTH_CLOSE
