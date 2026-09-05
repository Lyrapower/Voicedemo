"""
Momentum Sticker — independent watcher sidecar (report-only).

Low-threshold, high-recall anomaly detector:
  volume spike + price breakout + options activity

Does NOT touch pool scan / signal funnel. Outputs go to sentinel attention budget.
Egress uses trade-action blocklist (same lexicon as contract_gate).
"""

from __future__ import annotations

import datetime
import logging
import os
import re
from typing import Optional

import requests

from sentinel_attention import add_attention

logger = logging.getLogger("MomentumSticker")

TRADE_ACTION_OUTPUT = re.compile(
    r"建仓|做多|做空|买入|卖出|加仓|开仓|平仓|开多|开空|平多|平空|下单",
    re.I,
)

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_DATA_BASE = os.getenv("ALPACA_DATA_BASE", "https://data.alpaca.markets")
ALPACA_DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "12"))

DEFAULT_SYMBOLS = (
    "MU,MRVL,AMD,HOOD,DELL,APA,OXY,IONQ,NVDA,TSLA,PLTR,COIN,IREN,CRDO,QCOM,WULF,HUT"
)


def _headers() -> dict:
    return {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}


def _sanitize_report(text: str) -> Optional[str]:
    if TRADE_ACTION_OUTPUT.search(text):
        logger.warning("momentum report blocked by trade-action lexicon")
        return None
    footer = "\n—\n异动观察 report-only | 不产生信号 | sentinel 注意力预算"
    return text + footer


def _fetch_bars(session: requests.Session, symbol: str, days: int = 25) -> list[dict]:
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=days + 5)
    url = (
        f"{ALPACA_DATA_BASE}/v2/stocks/{symbol}/bars"
        f"?timeframe=1Day&start={start.date().isoformat()}&limit={days + 5}&feed={ALPACA_DATA_FEED}"
    )
    r = session.get(url, headers=_headers(), timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json().get("bars") or []


def _fetch_option_volume(session: requests.Session, symbol: str) -> int:
    """Sum today's option day-bar volume from indicative snapshots (low bar)."""
    url = f"{ALPACA_DATA_BASE}/v1beta1/options/snapshots/{symbol}?feed=indicative&limit=100"
    r = session.get(url, headers=_headers(), timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        return 0
    snaps = (r.json().get("snapshots") or {})
    total = 0
    for snap in snaps.values():
        bar = snap.get("dailyBar") or snap.get("daily_bar") or {}
        total += int(bar.get("v") or bar.get("volume") or 0)
    return total


def _score_symbol(session: requests.Session, symbol: str, cfg: dict) -> Optional[dict]:
    bars = _fetch_bars(session, symbol, days=cfg.get("lookback_days", 20))
    if len(bars) < 10:
        return None
    vols = [float(b.get("v", 0)) for b in bars]
    closes = [float(b.get("c", 0)) for b in bars]
    today_vol = vols[-1]
    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
    vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0
    high_n = max(closes[:-1]) if len(closes) > 1 else closes[-1]
    price = closes[-1]
    breakout = (price / high_n - 1) if high_n > 0 else 0
    opt_vol = _fetch_option_volume(session, symbol)
    opt_baseline = cfg.get("state", {}).get("opt_vol_baseline", {}).get(symbol, opt_vol or 1)
    opt_ratio = opt_vol / opt_baseline if opt_baseline > 0 else 0

    vol_thr = float(cfg.get("vol_ratio_min", 1.3))
    breakout_thr = float(cfg.get("breakout_min", 0.01))
    opt_thr = float(cfg.get("opt_vol_ratio_min", 1.2))
    hits = []
    if vol_ratio >= vol_thr:
        hits.append(f"放量×{vol_ratio:.2f}")
    if breakout >= breakout_thr:
        hits.append(f"突破+{breakout:.1%}")
    if opt_ratio >= opt_thr and opt_vol > 0:
        hits.append(f"期权量×{opt_ratio:.2f}")

    if len(hits) < int(cfg.get("min_hits", 2)):
        return None
    return {
        "symbol": symbol,
        "price": price,
        "vol_ratio": round(vol_ratio, 2),
        "breakout": round(breakout, 4),
        "opt_vol": opt_vol,
        "opt_ratio": round(opt_ratio, 2),
        "hits": hits,
    }


def check_momentum_sticker(target: dict, state: dict, session: requests.Session) -> dict:
    """Watcher entrypoint — one poll cycle for all configured symbols."""
    name = target.get("name", "MomentumSticker")
    symbols = [s.strip().upper() for s in target.get("symbols", DEFAULT_SYMBOLS.split(",")) if s.strip()]
    priority = target.get("priority", "normal")
    cooldown = int(target.get("cooldown_sec", 1800))
    now = datetime.datetime.now().astimezone()
    state["last_check"] = now.isoformat()
    last_fire = state.get("last_fire", {})

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        state["fail"] = state.get("fail", 0) + 1
        state["error"] = "Alpaca keys missing"
        return state

    state["fail"] = 0
    opt_baselines = state.setdefault("opt_vol_baseline", {})
    fired = []

    for sym in symbols:
        try:
            hit = _score_symbol(
                session,
                sym,
                {
                    "vol_ratio_min": target.get("vol_ratio_min", 1.3),
                    "breakout_min": target.get("breakout_min", 0.01),
                    "opt_vol_ratio_min": target.get("opt_vol_ratio_min", 1.2),
                    "min_hits": target.get("min_hits", 2),
                    "lookback_days": target.get("lookback_days", 20),
                    "state": state,
                },
            )
            if hit and opt_baselines.get(sym) is None and hit["opt_vol"] > 0:
                opt_baselines[sym] = hit["opt_vol"]
            elif hit and hit["opt_vol"] > 0:
                opt_baselines[sym] = max(int(opt_baselines.get(sym, 1)), hit["opt_vol"])

            if not hit:
                continue
            last_ts = last_fire.get(sym, 0)
            if datetime.datetime.now().timestamp() - last_ts < cooldown:
                continue

            detail = (
                f"{sym} ${hit['price']:.2f} | "
                + " | ".join(hit["hits"])
                + f" | opt_vol={hit['opt_vol']}"
            )
            report = _sanitize_report(f"📌 Momentum Sticker\n{detail}")
            if not report:
                continue

            add_attention(
                source="momentum_sticker",
                symbol=sym,
                signal="momentum_anomaly",
                detail=detail,
                priority=priority,
                tags=hit["hits"],
            )
            last_fire[sym] = datetime.datetime.now().timestamp()
            fired.append(sym)
            events = state.setdefault("events", [])
            events.append(
                {
                    "kind": "Momentum异动",
                    "detail": report,
                    "sym": sym,
                    "note": " · ".join(hit["hits"]),
                    "hit": hit,
                }
            )
            logger.info("[%s] anomaly %s: %s", name, sym, detail)
        except Exception as e:
            logger.error("[%s] %s scan failed: %s", name, sym, e)

    state["last_fire"] = last_fire
    state["last_fired"] = fired
    return state
