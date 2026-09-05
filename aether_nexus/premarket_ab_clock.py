"""A/B ledger clock — formal 30d window start after architecture cutover."""
from __future__ import annotations

AB_LEDGER_START_DATE = "2026-07-15"
WARMUP_DATES = frozenset({"2026-07-14"})


def is_warmup_day(trade_date: str) -> bool:
    return trade_date in WARMUP_DATES


def is_scorable_day(trade_date: str, *, void: bool = False) -> bool:
    if void or is_warmup_day(trade_date):
        return False
    return trade_date >= AB_LEDGER_START_DATE


def ab_ledger_meta(trade_date: str, *, void: bool = False) -> dict[str, str | bool]:
    warmup = is_warmup_day(trade_date)
    return {
        "ab_ledger_start": AB_LEDGER_START_DATE,
        "warmup": warmup,
        "scorable": is_scorable_day(trade_date, void=void),
    }
