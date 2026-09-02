"""Stage 1 — mechanical gates (no LLM)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from offpool_coach import config as cfg


def _mid(bid: float, ask: float) -> float:
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 4)
    return 0.0


def gate_momentum(symbol: str, spot: float, *, today: dt.date | None = None) -> tuple[bool, str]:
    """Reject extended / already-ran names using history when available."""
    try:
        from aether_dryrun import get_stock_history
        import numpy as np
    except ImportError:
        return True, "momentum_skip:no_history_module"

    hist, _prov = get_stock_history(symbol)
    if hist is None or hist.empty or len(hist) < 21:
        return True, "momentum_skip:insufficient_history"

    closes = hist["Close"].astype(float).values
    ret_20 = (closes[-1] - closes[-21]) / closes[-21] if closes[-21] > 0 else 0.0
    if ret_20 > cfg.MOM_CEILING:
        return False, f"GATE_MOMENTUM:ret_20={ret_20:.2%}>{cfg.MOM_CEILING:.0%}"

    mean_20 = float(np.mean(closes[-20:]))
    atr_proxy = float(np.mean(np.abs(np.diff(closes[-15:])))) if len(closes) >= 15 else 0.0
    if mean_20 > 0 and atr_proxy > 0:
        ext = (spot - mean_20) / atr_proxy
        if ext > cfg.EXT_ATR:
            return False, f"GATE_MOMENTUM:ext_atr={ext:.2f}>{cfg.EXT_ATR}"

    return True, f"momentum_ok:ret_20={ret_20:.2%}"


def gate_liquidity(row: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """Liquidity gate. OI null ≠ pass: degrade to spread-only + oi_unverified."""
    spread = float(row.get("spread_pct") or 1.0)
    oi_src = str(row.get("oi_source") or "")
    oi_val = row.get("open_interest")
    oi_unverified = oi_src in ("missing_in_snapshot", "missing") or oi_val is None

    meta: dict[str, Any] = {
        "oi_unverified": oi_unverified,
        "oi_available": not oi_unverified,
        "oi_source": oi_src,
        "spread_pct": spread,
        "gate_mode": "spread_only+oi_unverified" if oi_unverified else "spread+oi",
    }

    if spread > cfg.MAX_SPREAD_PCT:
        return False, f"GATE_LIQUIDITY:spread={spread:.2%}>{cfg.MAX_SPREAD_PCT:.0%}", meta

    if not oi_unverified:
        oi = int(oi_val or 0)
        if oi < cfg.MIN_OI:
            return False, f"GATE_LIQUIDITY:oi={oi}<{cfg.MIN_OI}", meta

    bid = float(row.get("bid") or 0)
    ask = float(row.get("ask") or 0)
    if bid <= 0 or ask <= 0 or bool(row.get("quote_stale")):
        return False, "GATE_LIQUIDITY:stale_or_missing_quote", meta

    if oi_unverified:
        return True, "liquidity_ok:spread_only;oi_unverified", meta
    return True, "liquidity_ok", meta


def gate_event(symbol: str, *, today: dt.date | None = None) -> tuple[bool, str, bool]:
    """Earnings within 2 sessions → event_lane tag, not hard reject."""
    today = today or dt.datetime.now(cfg.EST).date()
    try:
        from earnings_catalyst import earnings_in_window

        hit = earnings_in_window(symbol, min_days=0, max_days=2, today=today)
        if hit:
            return True, f"GATE_EVENT:earnings_{hit.get('date')}", True
    except Exception as exc:  # M4: surface lookup failure instead of silent `event_ok`
        import logging

        logging.getLogger(__name__).warning("gate_event lookup failed for %s: %s", symbol, exc)
        return True, "event_skip:lookup_failed", False
    return True, "event_ok", False


def gate_staleness(scan_time: dt.datetime, *, now: dt.datetime | None = None) -> tuple[bool, str, float | None]:
    now = now or dt.datetime.now(scan_time.tzinfo or dt.timezone.utc)
    age_min = (now - scan_time).total_seconds() / 60.0
    if age_min > cfg.MAX_QUOTE_AGE_MIN:
        return False, f"GATE_STALENESS:age_min={age_min:.1f}>{cfg.MAX_QUOTE_AGE_MIN}", age_min
    return True, f"staleness_ok:age_min={age_min:.1f}", age_min


def apply_stage1(
    symbol: str,
    row: dict[str, Any],
    *,
    scan_time: dt.datetime,
    today: dt.date,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Return gate audit fields for one symbol's best contract row."""
    spot = float(row.get("spot") or 0)
    passes: list[str] = []
    rejects: list[str] = []
    skips: list[str] = []  # M3: gates skipped due to unavailable data (distinct from pass)

    ok, reason = gate_momentum(symbol, spot, today=today)
    # M3: a momentum_skip:* reason means the gate could not run (no/thin history),
    # not that it genuinely passed. Track separately so audit can distinguish.
    if reason.startswith("momentum_skip:"):
        skips.append(reason)
    else:
        (passes if ok else rejects).append(reason)

    ok, reason, liq_meta = gate_liquidity(row)
    (passes if ok else rejects).append(reason)

    ok, reason, event_lane = gate_event(symbol, today=today)
    passes.append(reason)

    ok, reason, age_min = gate_staleness(scan_time, now=now)
    (passes if ok else rejects).append(reason)

    return {
        "event_lane": event_lane,
        "gate_pass": passes,
        "gate_reject": rejects,
        "gate_skip": skips,
        "momentum_skipped": bool(skips),
        "eligible": len(rejects) == 0,
        "quote_age_minutes": age_min,
        "liquidity_meta": liq_meta,
    }
