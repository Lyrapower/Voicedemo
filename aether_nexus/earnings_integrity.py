"""E-1 earnings lane integrity gate — block display until engine faults cleared."""
from __future__ import annotations

import re

_BARE = re.compile(r"^(WARN|ERROR)\.?$", re.I)
# unverified_catalyst = per-symbol skip (E-1 design), NOT an engine-blocking fault.
_BLOCKING = (
    "theta_ratio caps invalid",
    "annualized theta mismatch",
)


def sanitize_anomaly_flag(flag: str) -> str | None:
    text = str(flag or "").strip()
    if not text or _BARE.match(text):
        return None
    if text in ("WARN", "ERROR", "WARN:", "ERROR:"):
        return None
    return text


def earnings_engine_blocked(flags: list[str] | None = None) -> tuple[bool, list[str]]:
    """Return (blocked, reasons). blocked=True → show 引擎异常 banner."""
    reasons: list[str] = []
    for raw in flags or []:
        clean = sanitize_anomaly_flag(raw)
        if clean is None and raw:
            reasons.append(f"bare_flag:{raw}")
            continue
        if clean and any(tok in clean for tok in _BLOCKING):
            reasons.append(clean)
    return (len(reasons) > 0, reasons)
