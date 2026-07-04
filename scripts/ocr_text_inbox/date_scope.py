"""Locked date scope for OCR_Text_Inbox (do not re-OCR before Aug 2025)."""

from __future__ import annotations

from datetime import date, datetime, timezone

# Inclusive: 2025-08-01 through 2026-05-20
RANGE_START = date(2025, 8, 1)
RANGE_END = date(2026, 5, 20)

MONTHS = [f"2025-{m:02d}" for m in range(8, 13)] + [f"2026-{m:02d}" for m in range(1, 6)]
MONTH_SET = set(MONTHS)

# Mojibake re-OCR pass: Sept 2025 through May 2026 only (skip 2025-08)
MOJIBAKE_MONTHS = [f"2025-{m:02d}" for m in range(9, 13)] + [f"2026-{m:02d}" for m in range(1, 6)]
MOJIBAKE_MONTH_SET = set(MOJIBAKE_MONTHS)


def range_start_utc() -> datetime:
    return datetime(2025, 8, 1, tzinfo=timezone.utc)


def range_end_exclusive_utc() -> datetime:
    """First instant after the last included day (2026-05-20)."""
    return datetime(2026, 5, 21, tzinfo=timezone.utc)


def in_range(d: date) -> bool:
    return RANGE_START <= d <= RANGE_END


def in_range_dt(dt: datetime) -> bool:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return RANGE_START <= dt.astimezone(timezone.utc).date() <= RANGE_END
