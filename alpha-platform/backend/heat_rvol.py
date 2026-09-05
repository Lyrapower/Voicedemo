"""Heat RET 5M window + RVOL gate (quote snapshots). Zero LLM."""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

RVOL_GATE_THRESH = 1.5
RVOL_LOOKBACK = 21  # last 21 cumulative quote volumes
RET5M_WINDOW_S = 300
GATE_CODE = {"pass": 1.0, "fail": 0.0, "warming": -1.0, "auction": -2.0}
AUCTION_OPEN = (dt.time(9, 30), dt.time(9, 35))
AUCTION_CLOSE = (dt.time(15, 55), dt.time(16, 0))


def decode_gate(value: Any) -> str:
    if value is None:
        return "warming"
    if isinstance(value, str):
        v = value.strip().lower()
        if v in GATE_CODE:
            return v
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "warming"
    if n <= -1.5:
        return "auction"
    if n <= -0.5:
        return "warming"
    if n >= 0.5:
        return "pass"
    return "fail"


def encode_gate(gate: str) -> float:
    return GATE_CODE.get(gate, -1.0)


def _as_et(now: Any) -> dt.datetime:
    if now is None:
        return dt.datetime.now(ET)
    if isinstance(now, (int, float)):
        return dt.datetime.fromtimestamp(float(now), tz=ET)
    if isinstance(now, dt.datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=ET)
        return now.astimezone(ET)
    return dt.datetime.now(ET)


def is_auction_window(now: Any = None) -> bool:
    t = _as_et(now).time()
    return (AUCTION_OPEN[0] <= t < AUCTION_OPEN[1]) or (AUCTION_CLOSE[0] <= t < AUCTION_CLOSE[1])


def apply_session_gate(gate: str, now: Any = None) -> str:
    if is_auction_window(now):
        return "auction"
    return gate


def gate_rank(gate: Any) -> int:
    g = decode_gate(gate)
    return {"pass": 0, "warming": 1, "auction": 1, "fail": 2}.get(g, 1)


def heat_sort_key(row: dict[str, Any]) -> tuple:
    """pass × RET 5M, then warming/auction, then fail; null RET sinks."""
    ret = row.get("ret5m")
    gate = row.get("rvol_gate", row.get("gate"))
    return (
        gate_rank(gate),
        0 if ret is not None else 1,
        -(float(ret) if ret is not None else 0.0),
        int(row.get("env_order") or 999),
    )


def ret_5m_from_quote_window(rows: list[tuple[int, float]]) -> float | None:
    """rows = (ts, close) in ts>=now-300s window, oldest first. <2 bars → None."""
    if len(rows) < 2:
        return None
    c0 = float(rows[0][1])
    c1 = float(rows[-1][1])
    if not c0:
        return None
    return (c1 - c0) / c0


def rvol_from_cumulative(vols: list[float]) -> tuple[float | None, str, bool]:
    """Last 21 cumulative quote volumes, oldest first.

    20 interval volumes; rvol = last / median(20).
    Negative delta → that interval NULL; if last is NULL, rvol=NULL + warn.
    <21 bars → (None, warming, False).
    """
    if len(vols) < RVOL_LOOKBACK:
        return None, "warming", False
    use = [float(v or 0) for v in vols[-RVOL_LOOKBACK:]]
    deltas: list[float | None] = []
    neg = False
    for i in range(1, len(use)):
        d = use[i] - use[i - 1]
        if d < 0:
            neg = True
            deltas.append(None)
        else:
            deltas.append(d)
    last = deltas[-1] if deltas else None
    valid = [d for d in deltas if d is not None]
    if last is None or not valid:
        return None, "warming", neg
    med = statistics.median(valid)
    if med <= 0:
        rvol = 0.0 if last == 0 else None
        if rvol is None:
            return None, "warming", neg
    else:
        rvol = last / med
    gate = "pass" if rvol >= RVOL_GATE_THRESH else "fail"
    return rvol, gate, neg
