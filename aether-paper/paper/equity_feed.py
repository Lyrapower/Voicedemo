"""美股现货 mark —— 供 paper 引擎 mark-to-market / 止损。
   优先 yfinance(无需 key); 可选 Alpaca latest trade。"""
from __future__ import annotations

import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Iterable

logger = logging.getLogger(__name__)

try:
    import certifi
except ImportError:
    certifi = None  # type: ignore


def _ssl_ctx() -> ssl.SSLContext:
    if certifi:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def _get_json(url: str, headers: dict | None = None, timeout: int = 12) -> dict | list | None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "aether-paper/1.0", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        # M7: surface feed failures instead of silent None — Alpaca failure was
        # previously invisible to the engine.
        logger.warning("equity_feed _get_json failed %s: %s", url, exc)
        return None


def _alpaca_headers() -> dict | None:
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        return None
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def spot_price_alpaca(symbol: str) -> float | None:
    headers = _alpaca_headers()
    if not headers:
        return None
    base = os.getenv("ALPACA_DATA_BASE", "https://data.alpaca.markets")
    url = f"{base}/v2/stocks/{symbol.upper()}/trades/latest"
    data = _get_json(url, headers=headers)
    if not isinstance(data, dict):
        return None
    trade = data.get("trade") or {}
    p = trade.get("p") or trade.get("price")
    return round(float(p), 2) if p else None


def spot_price_yfinance(symbol: str) -> float | None:
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance unavailable for %s — no equity mark", symbol)
        return None
    try:
        t = yf.Ticker(symbol.upper())
        info = t.fast_info
        p = getattr(info, "last_price", None)
        if p is None:
            # M7: only previous_close available → mark is stale (yesterday's close).
            # Still return it so the engine can mark-to-market, but warn visibly.
            p = getattr(info, "previous_close", None)
            if p is not None:
                logger.warning("equity_feed %s using stale previous_close (no live price)", symbol)
        if p is None:
            hist = t.history(period="1d")
            if hist is not None and not hist.empty:
                p = float(hist["Close"].iloc[-1])
        return round(float(p), 2) if p else None
    except Exception as exc:
        # M7: log instead of silent return None
        logger.warning("equity_feed yfinance failed %s: %s", symbol, exc)
        return None


def spot_price(symbol: str) -> float | None:
    p = spot_price_alpaca(symbol)
    if p is not None:
        return p
    return spot_price_yfinance(symbol)


def marks(symbols: Iterable[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for sym in symbols:
        s = str(sym).upper()
        if not s or s.endswith("-USD"):
            continue
        p = spot_price(s)
        if p is not None:
            out[s] = p
        time.sleep(0.12)
    return out
