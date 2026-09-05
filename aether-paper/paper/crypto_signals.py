"""Crypto 每日信号 —— 独立于 Grid scan，Coinbase 日线动量。"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
from typing import Any

from . import crypto_feed

CRYPTO_UNIVERSE = ["BTC-USD", "ETH-USD", "SOL-USD"]
MIN_5D_RETURN = float(os.getenv("CRYPTO_SIGNAL_MIN_RET", "0.015"))
WANT_PCT = float(os.getenv("CRYPTO_SIGNAL_WANT_PCT", "0.10"))


def _day_key() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def signal_key(day: str, symbol: str) -> str:
    return hashlib.sha256(f"{day}|{symbol}|crypto_daily".encode()).hexdigest()[:16]


def _five_day_return(symbol: str) -> tuple[float | None, float | None]:
    candles = crypto_feed.daily_candles(symbol, days=8)
    if not candles or len(candles) < 6:
        return None, None
    closes = [float(c["close"]) for c in candles[-6:]]
    ret = (closes[-1] / closes[0]) - 1.0
    return ret, closes[-1]


def generate_daily_signals(*, day: str | None = None) -> list[dict[str, Any]]:
    """One signal max per symbol per UTC day if 5d momentum passes threshold."""
    day = day or _day_key()
    out: list[dict[str, Any]] = []
    for sym in CRYPTO_UNIVERSE:
        ret, last = _five_day_return(sym)
        if ret is None or last is None:
            continue
        if ret < MIN_5D_RETURN:
            continue
        want = min(WANT_PCT, 0.20)
        out.append(
            {
                "symbol": sym,
                "want_pct": want,
                "score": round(ret * 100, 2),
                "scan_time": f"{day}T09:00:00Z",
                "scan_mode": "crypto_daily",
                "label": "crypto_momentum",
                "reason": f"crypto_daily:5d_ret={ret:.2%}:momentum",
                "ref_price": last,
                "key": signal_key(day, sym),
            }
        )
    return out
