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
import sys
from pathlib import Path
from typing import Optional

import requests

from sentinel_attention import add_attention

logger = logging.getLogger("MomentumSticker")

try:
    _gw = Path(__file__).resolve().parents[1] / "grid-sovereign-runtime" / "gateway"
    if str(_gw) not in sys.path:
        sys.path.insert(0, str(_gw))
    from contract_lexicon import TRADE_ACTION_OUTPUT  # type: ignore
except ImportError:
    TRADE_ACTION_OUTPUT = re.compile(
        r"建仓|做多|做空|买入|卖出|加仓|开仓|平仓|开多|开空|平多|平空|下单",
        re.I,
    )

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_DATA_BASE = os.getenv("ALPACA_DATA_BASE", "https://data.alpaca.markets")
ALPACA_DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "12"))


def _headers() -> dict:
    return {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}


def _sanitize_report(text: str) -> Optional[str]:
    if TRADE_ACTION_OUTPUT.search(text):
        logger.warning("momentum report blocked by trade-action lexicon")
        return None
    footer = "\n—\n异动观察 report-only | 不产生信号 | sentinel 注意力预算"
    return text + footer


def resolve_momentum_symbols(target: dict) -> list[str]:
    """Pool symbols from aether_nexus + optional extra_symbols in toml."""
    nexus = Path(__file__).resolve().parents[1] / "aether_nexus"
    if str(nexus) not in sys.path:
        sys.path.insert(0, str(nexus))
    try:
        from pool_config import pool_symbols  # type: ignore

        base = pool_symbols()
    except Exception as exc:
        logger.warning("pool_config unavailable: %s", exc)
        base = []
    extra = target.get("extra_symbols") or []
    if isinstance(extra, str):
        extra = [s.strip() for s in extra.split(",") if s.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for sym in list(base) + [str(x).strip().upper() for x in extra]:
        u = str(sym).strip().upper()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _opt_baseline(state: dict, symbol: str, today_vol: int, lookback: int = 20) -> float:
    """Rolling median baseline — avoids max-only baseline that never decays."""
    hist_map = state.setdefault("opt_vol_history", {})
    hist = hist_map.setdefault(symbol, [])
    if today_vol > 0:
        hist.append(int(today_vol))
        hist[:] = hist[-lookback:]
    if len(hist) >= 3:
        s = sorted(hist)
        mid = len(s) // 2
        if len(s) % 2:
            return float(s[mid])
        return float((s[mid - 1] + s[mid]) / 2)
    return float(today_vol or hist[-1] if hist else 1)


def _fetch_bars(session: requests.Session, symbol: str, days: int = 25) -> list[dict]:
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=days + 5)
    # 必须 sort=desc:asc+start+limit 会吃到最旧 N 根;调用方用 [-1]=今日
    url = (
        f"{ALPACA_DATA_BASE}/v2/stocks/{symbol}/bars"
        f"?timeframe=1Day&start={start.date().isoformat()}&limit={days + 5}"
        f"&feed={ALPACA_DATA_FEED}&adjustment=raw&sort=desc"
    )
    r = session.get(url, headers=_headers(), timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    bars = r.json().get("bars") or []
    bars.reverse()
    return bars


def _fetch_option_volume(session: requests.Session, symbol: str) -> int:
    url = f"{ALPACA_DATA_BASE}/v1beta1/options/snapshots/{symbol}?feed=indicative&limit=100"
    r = session.get(url, headers=_headers(), timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        return 0
    snaps = r.json().get("snapshots") or {}
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
    state = cfg.get("state") or {}
    opt_baseline = _opt_baseline(state, symbol, opt_vol)
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
    name = target.get("name", "MomentumSticker")
    symbols = resolve_momentum_symbols(target)
    priority = target.get("priority", "normal")
    cooldown = int(target.get("cooldown_sec", 1800))
    state["last_check"] = datetime.datetime.now().astimezone().isoformat()
    state["resolved_symbols"] = symbols
    last_fire = state.get("last_fire", {})

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        state["fail"] = state.get("fail", 0) + 1
        state["error"] = "Alpaca keys missing"
        return state

    state["fail"] = 0
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
