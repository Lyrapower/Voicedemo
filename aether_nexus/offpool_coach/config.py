"""Offpool coach trial tunables — spec §9."""
from __future__ import annotations

import datetime as dt
import os
from typing import Any

from aether_shared import EST

from offpool_coach import risk_budget as rb

from offpool_coach.schema import SCHEMA_VERSION as _SCHEMA_VERSION

SCHEMA_VERSION = _SCHEMA_VERSION

EXEC_WINDOW_PST = os.getenv("EXEC_WINDOW_PST", "07:15")
PREMARKET_WINDOW_PST = os.getenv("PREMARKET_WINDOW_PST", "06:20")
# First calendar day of trial — no catch-up runs before this date (PST).
TRIAL_START_DATE = os.getenv("OFFPOOL_COACH_TRIAL_START", "2026-07-17").strip()

MOM_CEILING = float(os.getenv("MOM_CEILING", "0.25"))
EXT_ATR = float(os.getenv("EXT_ATR", "2.5"))
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.08"))
MIN_OI = int(os.getenv("MIN_OI", "500"))
MAX_IV = float(os.getenv("DRYRUN_MAX_IV", os.getenv("MAX_IV", "0.80")))
MIN_ADV_USD = float(os.getenv("MIN_ADV_USD", "50000000"))
MAX_QUOTE_AGE_MIN = float(os.getenv("MAX_QUOTE_AGE_MIN", "10"))
STAGE1_MAX = int(os.getenv("STAGE1_MAX", "12"))
# Each PREMARKET / EXECUTION window must emit >= this many coach picks (mechanical fallback if Fable empty).
MIN_COACH_PICKS_PER_WINDOW = max(1, int(os.getenv("MIN_COACH_PICKS_PER_WINDOW", "1")))

# Fable scoring caps — stage4 enforced; prompt must match.
LIQUIDITY_SCORE_CAP_OI_UNVERIFIED = int(os.getenv("LIQUIDITY_SCORE_CAP_OI_UNVERIFIED", "4"))
STRUCTURE_SCORE_CAP_ANCHOR_MISSING = int(os.getenv("STRUCTURE_SCORE_CAP_ANCHOR_MISSING", "3"))

SLIP_BPS = float(os.getenv("SLIP_BPS", "15"))
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "5"))

RISK_BUDGET_PCT = rb.RISK_BUDGET_PCT
FUSE_PREMIUM_PCT = rb.FUSE_PREMIUM_PCT
STOP_AUTHORITY = rb.STOP_AUTHORITY
STOP_AUTHORITY_NOTE = rb.STOP_AUTHORITY_NOTE
SIZING_FORMULA = rb.SIZING_FORMULA

RISK_BUDGET_USD: float | None = None
ACCOUNT_EQUITY_USD: float | None = None
RISK_BUDGET_AS_OF: str | None = None
_risk_snapshot: dict[str, Any] | None = None

FABLE_CLI_MODEL = os.getenv("OFFPOOL_COACH_CLI_MODEL", os.getenv("FABLE_CLI_MODEL", "claude-fable-5"))
OUTPUT_DIR = os.getenv(
    "OFFPOOL_COACH_DIR",
    str(__import__("pathlib").Path(__file__).resolve().parent.parent / "traces" / "offpool_coach"),
)


def refresh_risk_budget(*, trade_date: dt.date | None = None) -> dict[str, Any]:
    """Resolve RISK_BUDGET_USD from paper account; write snapshot with as_of date."""
    global RISK_BUDGET_USD, ACCOUNT_EQUITY_USD, RISK_BUDGET_AS_OF, _risk_snapshot
    snap = rb.resolve_risk_budget(trade_date=trade_date)
    _risk_snapshot = snap
    RISK_BUDGET_USD = snap.get("risk_budget_usd")
    ACCOUNT_EQUITY_USD = snap.get("account_equity_usd")
    RISK_BUDGET_AS_OF = snap.get("as_of")
    return snap


def risk_budget_block() -> dict[str, Any]:
    if _risk_snapshot is None:
        refresh_risk_budget(trade_date=dt.datetime.now(EST).date())
    assert _risk_snapshot is not None
    return rb.risk_budget_for_payload(_risk_snapshot)
