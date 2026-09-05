"""Daily daemon scheduling — fire once at or after HH:MM (not exact minute).

Patch R5.4.x: replaces `now.hour == h and now.minute == m` loops that skip
the whole trading day when the 20–30s poll misses the single minute slot.
"""
from __future__ import annotations

import datetime as dt


def parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.strip().split(":")
    return int(hour), int(minute)


def slot_due(now: dt.datetime, hour: int, minute: int, *, grace_minutes: int = 180) -> bool:
    """True when local time is within the slot's grace window.

    Fires at or after HH:MM (so a 20–30s poll can't miss the exact minute), but
    only up to `grace_minutes` after the slot. M12: previously True for the rest
    of the day, so a process restart after a partial failure (lost state write)
    could re-fire the same slot hours later. After the grace window the slot is
    treated as stale/missed and left to `schedule_catchup`.
    """
    now_m = now.hour * 60 + now.minute
    slot_m = hour * 60 + minute
    if now_m < slot_m:
        return False
    return (now_m - slot_m) <= grace_minutes


def minutes_past_slot(now: dt.datetime, hour: int, minute: int) -> int:
    """Minutes elapsed since HH:MM today (0 if not yet due)."""
    now_m = now.hour * 60 + now.minute
    slot_m = hour * 60 + minute
    return max(0, now_m - slot_m)
