#!/usr/bin/env python3
"""
Aether Nexus R5.4.1 — Data-Hardened Dry Run Scanner (integrated)

R5.4.1: Alpaca/Stooq/yfinance provider router, data health, trading-day gate.
Integration: dual Pool+BFS lines, perilla watchlist, IB candidate export, aether_shared schedule.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from io import StringIO
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
import requests
from dotenv import load_dotenv

from aether_shared import (
    AETHER_VERSION,
    EST,
    SCAN_MAX_DTE,
    SCAN_MAX_PRICE,
    SCAN_MIN_DTE,
    SCAN_MIN_PRICE,
    SCAN_POST_MARKET,
    SCAN_PRE_MARKET,
    SP500_URL,
    TOP_CANDIDATES,
    _telegram_configured,
    export_dryrun_candidates_to_ib,
)

try:
    import yfinance as yf  # fallback only
except Exception:  # pragma: no cover
    yf = None

load_dotenv()

# ======================== Paths ========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "dryrun_state")
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
EARNINGS_CACHE_PATH = os.path.join(STATE_DIR, "earnings_cache.json")
IV_HISTORY_PATH = os.path.join(STATE_DIR, "iv_history.json")
DATA_HEALTH_PATH = os.path.join(STATE_DIR, "data_health.json")
os.makedirs(STATE_DIR, exist_ok=True)

# ======================== Config ========================

# API keys / notifications
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DRYRUN_SCAN_MAX_SYMBOLS = int(os.getenv("DRYRUN_SCAN_MAX_SYMBOLS", os.getenv("SCAN_MAX_SYMBOLS", "0")))
SCAN_MODE = os.getenv("DRYRUN_SCAN_MODE", os.getenv("SCAN_MODE", "sp500")).lower().strip()
POOL_SCAN_ENABLED = os.getenv("POOL_SCAN_ENABLED", "true").lower() == "true"
POOL_SCAN_PRE_MARKET = os.getenv("POOL_SCAN_PRE_MARKET", "09:35")
POOL_SCAN_POST_MARKET = os.getenv("POOL_SCAN_POST_MARKET", "15:20")

PERILLA_SCAN_TIME = os.getenv("PERILLA_SCAN_TIME", "08:30")
PERILLA_REMINDER_MIN = int(os.getenv("PERILLA_REMINDER_MIN", "5"))
WATCHLIST_BUY_SCORE_MIN = float(os.getenv("WATCHLIST_BUY_SCORE_MIN", "35"))
WATCHLIST_BUY_REMINDER = os.getenv("WATCHLIST_BUY_REMINDER", "09:40")
WATCHLIST_BUY_REMINDER_PM = os.getenv("WATCHLIST_BUY_REMINDER_PM", "15:25")
MAX_SIGNAL_ROUNDS = int(os.getenv("DRYRUN_MAX_SIGNAL_ROUNDS", "90"))
DRYRUN_SCAN_ON_START = os.getenv("DRYRUN_SCAN_ON_START", "false").lower() == "true"

MIN_DELTA = float(os.getenv("DRYRUN_MIN_DELTA", os.getenv("MIN_DELTA", "0.25")))
MAX_DELTA = float(os.getenv("DRYRUN_MAX_DELTA", os.getenv("MAX_DELTA", "0.50")))
MIN_GAMMA = float(os.getenv("DRYRUN_MIN_GAMMA", os.getenv("MIN_GAMMA", "0.01")))
MAX_IV = float(os.getenv("DRYRUN_MAX_IV", os.getenv("MAX_IV", "0.80")))
MIN_VOLUME = int(os.getenv("DRYRUN_MIN_VOLUME", os.getenv("MIN_VOLUME", "10")))
MIN_OPEN_INTEREST = int(os.getenv("DRYRUN_MIN_OPEN_INTEREST", os.getenv("MIN_OPEN_INTEREST", "50")))
MAX_SPREAD_PCT = float(os.getenv("DRYRUN_MAX_SPREAD_PCT", os.getenv("MAX_SPREAD_PCT", "0.10")))

SCAN_MIN_PRICE = float(os.getenv("SCAN_MIN_PRICE", str(SCAN_MIN_PRICE)))
SCAN_MAX_PRICE = float(os.getenv("SCAN_MAX_PRICE", str(SCAN_MAX_PRICE)))
SCAN_MIN_DTE = int(os.getenv("SCAN_MIN_DTE", str(SCAN_MIN_DTE)))
SCAN_MAX_DTE = int(os.getenv("SCAN_MAX_DTE", str(SCAN_MAX_DTE)))
TOP_CANDIDATES = int(os.getenv("TOP_CANDIDATES", str(TOP_CANDIDATES)))
SCAN_MAX_SYMBOLS = DRYRUN_SCAN_MAX_SYMBOLS

# Cleaner data sources first; yfinance only as fallback.
DATA_PROVIDER_ORDER = [x.strip().lower() for x in os.getenv("DATA_PROVIDER_ORDER", "alpaca,stooq,yfinance").split(",") if x.strip()]
OPTION_PROVIDER_ORDER = [x.strip().lower() for x in os.getenv("OPTION_PROVIDER_ORDER", "alpaca,yfinance").split(",") if x.strip()]

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex")  # free equities = IEX; paid = sip
ALPACA_OPTION_FEED = os.getenv("ALPACA_OPTION_FEED", "indicative")  # free = indicative; paid = opra
ALPACA_DATA_BASE = os.getenv("ALPACA_DATA_BASE", "https://data.alpaca.markets")
ALPACA_TRADING_BASE = os.getenv("ALPACA_TRADING_BASE", "https://paper-api.alpaca.markets")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "12"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
HTTP_BACKOFF = float(os.getenv("HTTP_BACKOFF", "0.8"))
YF_SLEEP = float(os.getenv("YF_SLEEP", "0.6"))
STOOQ_SLEEP = float(os.getenv("STOOQ_SLEEP", "1.0"))  # stooq bans aggressive IPs; matters in sp500 mode
NEAR_STRIKES_PER_EXPIRY = int(os.getenv("NEAR_STRIKES_PER_EXPIRY", "5"))  # unified across providers

# Shared HTTP session (connection reuse)
SESSION = requests.Session()

_DEFAULT_POOL = "MU,MRVL,AMD,HOOD,DELL,APA,OXY,IONQ,NVDA,TSLA,PLTR,COIN"
POOL_SYMBOLS = [s.strip().upper() for s in os.getenv("POOL_SYMBOLS", _DEFAULT_POOL).split(",") if s.strip()]
POOL_SYMBOLS_SET = set(POOL_SYMBOLS)
CAPITAL_PER_TRADE = float(os.getenv("CAPITAL_PER_TRADE", "1000.0"))
RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", "0.05"))

THETA_RATIO_SHORT = float(os.getenv("THETA_RATIO_SHORT", "0.12"))
THETA_RATIO_MID = float(os.getenv("THETA_RATIO_MID", "0.08"))
THETA_RATIO_LONG = float(os.getenv("THETA_RATIO_LONG", "0.055"))
HV_RANK_WINDOW = int(os.getenv("HV_RANK_WINDOW", "21"))
IV_VALUE_WEIGHT = float(os.getenv("IV_VALUE_WEIGHT", "10"))

EARNINGS_WINDOW_MIN = int(os.getenv("EARNINGS_WINDOW_MIN", "3"))
EARNINGS_WINDOW_MAX = int(os.getenv("EARNINGS_WINDOW_MAX", "7"))
EARNINGS_SCORE_BOOST = float(os.getenv("EARNINGS_SCORE_BOOST", "10"))
EARNINGS_CACHE_DAYS = int(os.getenv("EARNINGS_CACHE_DAYS", "3"))

BFS_STAGE1_KEEP = int(os.getenv("BFS_STAGE1_KEEP", "60"))
BFS_STAGE2_KEEP = int(os.getenv("BFS_STAGE2_KEEP", "20"))
STAGE1_MIN_DOLLAR_VOL = float(os.getenv("STAGE1_MIN_DOLLAR_VOL", "20000000"))
STAGE1_SECTOR_CAP_DIV = int(os.getenv("STAGE1_SECTOR_CAP_DIV", "4"))
LOGGING_FIRST = os.getenv("LOGGING_FIRST", "true").lower() == "true"

MAX_EXPIRIES_PER_SYMBOL = int(os.getenv("MAX_EXPIRIES_PER_SYMBOL", "3"))

logger = logging.getLogger("AetherR541")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh = logging.FileHandler(os.path.join(STATE_DIR, "dryrun.log"))
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)

LAST_REASON_COUNTS: Dict[str, int] = {}
DATA_HEALTH: List[Dict[str, Any]] = []


# ======================== Small utilities ========================
def _atomic_write(filepath: str, data: Any) -> None:
    import tempfile

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=os.path.dirname(filepath), suffix=".tmp", delete=False) as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            tmp = f.name
        os.replace(tmp, filepath)
    except Exception as e:
        logger.error(f"写入失败 {filepath}: {e}")


def _record_health(provider: str, symbol: str, endpoint: str, ok: bool, reason: str = "") -> None:
    DATA_HEALTH.append({
        "time": dt.datetime.now(EST).isoformat(),
        "provider": provider,
        "symbol": symbol,
        "endpoint": endpoint,
        "ok": bool(ok),
        "reason": reason[:240],
    })
    # R5.4.1: trim in-memory list too, not just the file (24/7 loop -> unbounded growth otherwise)
    if len(DATA_HEALTH) > 1000:
        del DATA_HEALTH[:-500]
    if len(DATA_HEALTH) % 25 == 0:
        _atomic_write(DATA_HEALTH_PATH, DATA_HEALTH[-500:])


def _request_json(url: str, headers: Optional[dict] = None, params: Optional[dict] = None,
                  provider: str = "http", symbol: str = "", endpoint: str = "") -> Optional[dict]:
    last_err = ""
    for attempt in range(HTTP_RETRIES + 1):
        try:
            r = SESSION.get(url, headers=headers or {}, params=params or {}, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                _record_health(provider, symbol, endpoint, True)
                return r.json()
            last_err = f"HTTP {r.status_code}: {r.text[:160]}"
            if r.status_code in (401, 403):
                break
            if r.status_code == 429:
                time.sleep(HTTP_BACKOFF * (attempt + 1) * 2)
            else:
                time.sleep(HTTP_BACKOFF * (attempt + 1))
        except Exception as e:
            last_err = str(e)
            time.sleep(HTTP_BACKOFF * (attempt + 1))
    _record_health(provider, symbol, endpoint, False, last_err)
    return None


def _alpaca_headers() -> Optional[dict]:
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return None
    return {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}


def normalize_symbol_for_yf(symbol: str) -> str:
    return symbol.replace(".", "-").upper()


def normalize_symbol_for_stooq(symbol: str) -> str:
    return symbol.replace(".", "-").lower() + ".us"


# ======================== Watchlist ========================
def load_watchlist() -> dict:
    try:
        with open(WATCHLIST_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"watchlist.json 加载失败: {e}")
        return {"perilla_leaf": [], "perilla_score_boost": 15, "fda_catalysts": [], "fda_score_boost": 12}


def get_perilla_symbols(watchlist: dict) -> set:
    return {item.get("symbol", "").upper() for item in watchlist.get("perilla_leaf", []) if item.get("symbol")}


def get_fda_catalyst_map(watchlist: dict) -> Dict[str, dict]:
    today = dt.date.today()
    out: Dict[str, dict] = {}
    for item in watchlist.get("fda_catalysts", []):
        try:
            sym = item["symbol"].upper()
            event_date = dt.datetime.strptime(item["expected_date"], "%Y-%m-%d").date()
            days_to = (event_date - today).days
            if 0 <= days_to <= 30:
                out[sym] = {**item, "symbol": sym, "days_to_event": days_to}
        except (ValueError, KeyError):
            continue
    return out


def save_watchlist(watchlist: dict) -> None:
    _atomic_write(WATCHLIST_PATH, watchlist)


def verify_perilla_data_sources(watchlist: dict) -> None:
    """Mark perilla symbols verified after provider pull + DTE window check."""
    changed = False
    for item in watchlist.get("perilla_leaf", []):
        sym = str(item.get("symbol", "")).upper()
        if not sym:
            continue
        data = get_stock_data_light(sym)
        time.sleep(0.15)
        verified = False
        reason = ""
        if data:
            opts, _ = get_option_chain(sym, data["price"], data.get("hv", 0.3), q=0.0)
            if opts:
                for o in opts:
                    if SCAN_MIN_DTE <= o["dte"] <= SCAN_MAX_DTE:
                        verified = True
                        break
                if not verified:
                    reason = "no_expiry_in_dte_window"
            else:
                reason = "no_option_chain"
        else:
            reason = "no_stock_data"
        prev = item.get("data_source_verified")
        item["data_source_verified"] = verified
        item["data_verify_reason"] = "" if verified else reason
        item["data_verified_at"] = dt.datetime.now(EST).isoformat()
        if prev != verified:
            changed = True
    if changed:
        save_watchlist(watchlist)


# ======================== Market data: stocks/history ========================
def fetch_alpaca_history(symbol: str, days: int = 370) -> Optional[pd.DataFrame]:
    headers = _alpaca_headers()
    if not headers:
        return None
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=days + 10)
    url = f"{ALPACA_DATA_BASE}/v2/stocks/bars"
    params = {
        "symbols": symbol,
        "timeframe": "1Day",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "adjustment": "raw",
        "feed": ALPACA_DATA_FEED,
        "limit": 10000,
    }
    data = _request_json(url, headers=headers, params=params, provider="alpaca", symbol=symbol, endpoint="stock_bars")
    if not data:
        return None
    bars = (data.get("bars") or {}).get(symbol) or []
    if not bars:
        return None
    rows = []
    for b in bars:
        rows.append({
            "Date": pd.to_datetime(b.get("t")).date(),
            "Open": float(b.get("o", np.nan)),
            "High": float(b.get("h", np.nan)),
            "Low": float(b.get("l", np.nan)),
            "Close": float(b.get("c", np.nan)),
            "Volume": float(b.get("v", 0) or 0),
        })
    df = pd.DataFrame(rows).dropna(subset=["Close"])
    if df.empty:
        return None
    return df.set_index(pd.to_datetime(df["Date"]))[["Open", "High", "Low", "Close", "Volume"]]


def fetch_alpaca_latest_price(symbol: str) -> Optional[float]:
    headers = _alpaca_headers()
    if not headers:
        return None
    url = f"{ALPACA_DATA_BASE}/v2/stocks/{symbol}/trades/latest"
    params = {"feed": ALPACA_DATA_FEED}
    data = _request_json(url, headers=headers, params=params, provider="alpaca", symbol=symbol, endpoint="latest_trade")
    try:
        trade = data.get("trade") if data else None
        p = trade.get("p") if trade else None
        return float(p) if p and p > 0 else None
    except Exception:
        return None


def fetch_stooq_history(symbol: str) -> Optional[pd.DataFrame]:
    # Daily/EOD; cleaner fallback for HV/history, not intraday freshness.
    url = "https://stooq.com/q/d/l/"
    params = {"s": normalize_symbol_for_stooq(symbol), "i": "d"}
    try:
        r = SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
        time.sleep(STOOQ_SLEEP)
        if r.status_code != 200 or not r.text.strip() or "No data" in r.text[:80]:
            _record_health("stooq", symbol, "daily_csv", False, f"HTTP/data issue {r.status_code}")
            return None
        rows = list(csv.DictReader(io.StringIO(r.text)))
        if not rows:
            _record_health("stooq", symbol, "daily_csv", False, "empty csv")
            return None
        df = pd.DataFrame(rows)
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date", "Close"]).sort_values("Date")
        if len(df) < 30:
            _record_health("stooq", symbol, "daily_csv", False, f"too few rows {len(df)}")
            return None
        _record_health("stooq", symbol, "daily_csv", True)
        return df.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]].tail(370)
    except Exception as e:
        _record_health("stooq", symbol, "daily_csv", False, str(e))
        return None


def fetch_yfinance_history(symbol: str) -> Optional[pd.DataFrame]:
    if yf is None:
        return None
    try:
        ticker = yf.Ticker(normalize_symbol_for_yf(symbol))
        hist = ticker.history(period="1y", auto_adjust=False)
        time.sleep(YF_SLEEP)
        if hist is None or hist.empty:
            _record_health("yfinance", symbol, "history", False, "empty")
            return None
        _record_health("yfinance", symbol, "history", True)
        return hist[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    except Exception as e:
        _record_health("yfinance", symbol, "history", False, str(e))
        return None


def get_stock_history(symbol: str) -> Tuple[Optional[pd.DataFrame], str]:
    for provider in DATA_PROVIDER_ORDER:
        if provider == "alpaca":
            hist = fetch_alpaca_history(symbol)
        elif provider == "stooq":
            hist = fetch_stooq_history(symbol)
        elif provider == "yfinance":
            hist = fetch_yfinance_history(symbol)
        else:
            continue
        if hist is not None and not hist.empty:
            return hist, provider
    return None, "none"


def get_latest_price(symbol: str, hist: pd.DataFrame, hist_provider: str) -> Tuple[float, str]:
    if "alpaca" in DATA_PROVIDER_ORDER:
        p = fetch_alpaca_latest_price(symbol)
        if p and p > 0:
            return float(p), "alpaca_latest_trade"
    return float(hist["Close"].iloc[-1]), f"{hist_provider}_last_close"


# ======================== Options data ========================
def parse_occ_symbol(contract_symbol: str) -> Optional[dict]:
    # ROOT + YYMMDD + C/P + 8-digit strike*1000, e.g. AAPL260116C00200000
    s = contract_symbol.replace(" ", "")
    m = re.match(r"^(.+?)(\d{6})([CP])(\d{8})$", s)
    if not m:
        return None
    root, yymmdd, typ, strike_raw = m.groups()
    year = 2000 + int(yymmdd[:2])
    month = int(yymmdd[2:4])
    day = int(yymmdd[4:6])
    return {
        "root": root,
        "expiry": dt.date(year, month, day).isoformat(),
        "type": "call" if typ == "C" else "put",
        "strike": int(strike_raw) / 1000.0,
    }


def _snap_get_quote_value(q: dict, *names: str, default: float = 0.0) -> float:
    for n in names:
        v = q.get(n)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return default


def fetch_alpaca_option_chain(symbol: str, price: float) -> List[dict]:
    headers = _alpaca_headers()
    if not headers:
        return []
    today = dt.datetime.now(EST).date()
    url = f"{ALPACA_DATA_BASE}/v1beta1/options/snapshots/{symbol}"
    base_params = {
        "feed": ALPACA_OPTION_FEED,
        "type": "call",
        "expiration_date_gte": (today + dt.timedelta(days=SCAN_MIN_DTE)).isoformat(),
        "expiration_date_lte": (today + dt.timedelta(days=SCAN_MAX_DTE)).isoformat(),
        "strike_price_gte": round(price * 0.90, 2),
        "strike_price_lte": round(price * 1.15, 2),
        "limit": 1000,
    }

    # R5.4.1: follow next_page_token. Large chains (NVDA/TSLA) exceed 1000 even with filters;
    # the old code silently truncated.
    iterable: List[Tuple[str, dict]] = []
    page_token: Optional[str] = None
    for _page in range(10):  # hard cap: 10k contracts is more than enough post-filter
        params = dict(base_params)
        if page_token:
            params["page_token"] = page_token
        data = _request_json(url, headers=headers, params=params, provider="alpaca", symbol=symbol, endpoint="option_chain")
        if not data:
            break
        snapshots = data.get("snapshots") or data.get("data") or {}
        if isinstance(snapshots, list):
            iterable.extend((x.get("symbol") or x.get("contract_symbol") or "", x) for x in snapshots)
        else:
            iterable.extend(snapshots.items())
        page_token = data.get("next_page_token")
        if not page_token:
            break
    if not iterable:
        return []

    out: List[dict] = []
    for contract_symbol, snap in iterable:
        meta = parse_occ_symbol(contract_symbol)
        if not meta or meta["type"] != "call":
            continue
        # R5.4.1: skip adjusted contracts (e.g. NVDA1) — non-standard deliverables, strike semantics differ
        if meta["root"].upper() != symbol.upper():
            continue
        exp_date = dt.date.fromisoformat(meta["expiry"])
        dte = (exp_date - today).days
        if not (SCAN_MIN_DTE <= dte <= SCAN_MAX_DTE):
            continue
        strike = float(meta["strike"])
        if not (price * 0.94 <= strike <= price * 1.12):
            continue

        q = snap.get("latestQuote") or snap.get("latest_quote") or snap.get("quote") or {}
        t = snap.get("latestTrade") or snap.get("latest_trade") or snap.get("trade") or {}
        daybar = snap.get("dailyBar") or snap.get("daily_bar") or snap.get("bar") or {}
        greeks = snap.get("greeks") or {}

        bid = _snap_get_quote_value(q, "bp", "bid_price", "bid", default=0.0)
        ask = _snap_get_quote_value(q, "ap", "ask_price", "ask", default=0.0)
        last = _snap_get_quote_value(t, "p", "price", "last_price", default=0.0)
        volume = int(_snap_get_quote_value(daybar, "v", "volume", default=0.0))
        iv = _snap_get_quote_value(snap, "impliedVolatility", "implied_volatility", "iv", default=0.0)
        delta = _snap_get_quote_value(greeks, "delta", default=np.nan)
        gamma = _snap_get_quote_value(greeks, "gamma", default=np.nan)
        theta = _snap_get_quote_value(greeks, "theta", default=np.nan)

        quote_stale = bid <= 0 or ask <= 0
        if bid > 0 and ask > 0:
            option_price = (bid + ask) / 2.0
            price_source = "alpaca_mid"
        elif last > 0:
            option_price = last
            price_source = "alpaca_last"
        else:
            option_price = 0.0
            price_source = "missing"

        if any(math.isnan(x) for x in [delta, gamma, theta]) or iv <= 0 or option_price <= 0:
            # Keep parse strict: R5.4 does not invent Greeks for Alpaca chain unless yfinance fallback exists.
            continue

        out.append({
            "strike": round(strike, 2),
            "expiry": meta["expiry"],
            "dte": dte,
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "last_price": round(last, 2),
            "option_price": round(option_price, 4),
            "price_source": price_source,
            "quote_stale": quote_stale,
            "volume": volume,
            "open_interest": 0,
            "oi_source": "missing_in_snapshot",
            "iv": round(iv, 4),
            "iv_source": f"alpaca_{ALPACA_OPTION_FEED}",
            "delta": round(delta, 4),
            "gamma": round(gamma, 4),
            "theta": round(theta, 6),
            "gamma_theta_ratio": round(gamma / abs(theta), 4) if abs(theta) > 1e-8 else 0,
            "premium_dollars": round(option_price * 100, 2),
            "spread_pct": round((ask - bid) / ((ask + bid) / 2), 4) if (ask + bid) > 0 else 1.0,
            "theta_ratio": round(abs(theta) / option_price, 4) if option_price > 0 else 999,
            "data_provider": "alpaca",
        })
    # R5.4.1: unify candidate window with yfinance path — keep N strikes nearest 1.02x target
    # per expiry, so GTR percentile pools are comparable regardless of which provider won.
    if out:
        target = price * 1.02
        by_expiry: Dict[str, List[dict]] = {}
        for o in out:
            by_expiry.setdefault(o["expiry"], []).append(o)
        expiries = sorted(by_expiry.keys())[:MAX_EXPIRIES_PER_SYMBOL]
        trimmed: List[dict] = []
        for e in expiries:
            trimmed.extend(sorted(by_expiry[e], key=lambda o: abs(o["strike"] - target))[:NEAR_STRIKES_PER_EXPIRY])
        out = trimmed
        _theta_unit_sanity(symbol, price, out)

    _record_health("alpaca", symbol, "option_chain_parse", bool(out), f"contracts={len(out)}")
    return out


_THETA_CHECKED: set = set()


def _theta_unit_sanity(symbol: str, price: float, contracts: List[dict]) -> None:
    """R5.4.1 one-time per-symbol diagnostic: compare Alpaca theta vs our daily BS theta.

    If Alpaca returns annualized theta, theta_ratio would be ~365x off and the DTE cap
    would silently kill (or pass) everything. Log the ratio so it's visible in dryrun.log.
    """
    if symbol in _THETA_CHECKED or not contracts:
        return
    _THETA_CHECKED.add(symbol)
    c = contracts[0]
    try:
        T = max(c["dte"], 1) / 365.0
        bs = bs_greeks(price, c["strike"], T, RISK_FREE_RATE, max(c["iv"], 0.01))
        a_theta, b_theta = abs(c["theta"]), abs(float(bs["theta"]))
        if b_theta > 1e-8:
            ratio = a_theta / b_theta
            level = logging.WARNING if (ratio > 30 or ratio < 1 / 30) else logging.INFO
            logger.log(level, f"theta-unit check {symbol}: alpaca={c['theta']} bs_daily={bs['theta']} ratio={ratio:.1f} "
                              f"(~1 expected; ~365 means Alpaca theta is annualized -> theta_ratio caps invalid)")
    except Exception as e:
        logger.debug(f"theta-unit check failed {symbol}: {e}")


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> dict:
    if T <= 0 or sigma <= 0 or S <= 0:
        return {"price": 0, "delta": 0, "gamma": 0, "theta": 0, "iv": sigma}
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    def npdf(x: float) -> float:
        return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

    def ncdf(x: float) -> float:
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    disc_q = math.exp(-q * T)
    disc_r = math.exp(-r * T)
    price = S * disc_q * ncdf(d1) - K * disc_r * ncdf(d2)
    delta = disc_q * ncdf(d1)
    gamma = disc_q * npdf(d1) / (S * sigma * math.sqrt(T)) if S > 0 else 0
    theta_day = (-(S * disc_q * npdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * disc_r * ncdf(d2) + q * S * disc_q * ncdf(d1)) / 365
    return {"price": round(price, 4), "delta": round(delta, 4), "gamma": round(gamma, 4), "theta": round(theta_day, 6), "iv": round(sigma, 4)}


def fetch_yfinance_option_chain(symbol: str, price: float, hv_fallback: float, q: float = 0.0) -> List[dict]:
    if yf is None:
        return []
    try:
        ticker = yf.Ticker(normalize_symbol_for_yf(symbol))
        expirations = ticker.options or []
        today = dt.datetime.now(EST).date()
        valid_expiries = []
        for exp_str in expirations:
            try:
                dte = (dt.date.fromisoformat(exp_str) - today).days
            except ValueError:
                continue
            if SCAN_MIN_DTE <= dte <= SCAN_MAX_DTE:
                valid_expiries.append(exp_str)
            if len(valid_expiries) >= MAX_EXPIRIES_PER_SYMBOL:
                break
        out: List[dict] = []
        for expiry in valid_expiries:
            chain = ticker.option_chain(expiry)
            calls = chain.calls.copy()
            if calls.empty:
                continue
            exp_date = dt.date.fromisoformat(expiry)
            dte = (exp_date - today).days
            T = dte / 365.0
            target = price * 1.02
            calls["distance"] = abs(calls["strike"] - target)
            calls = calls.sort_values("distance").head(NEAR_STRIKES_PER_EXPIRY)
            for _, row in calls.iterrows():
                strike = float(row.get("strike", 0) or 0)
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                last = float(row.get("lastPrice", 0) or 0)
                volume = int(row.get("volume", 0) or 0)
                oi = int(row.get("openInterest", 0) or 0)
                chain_iv = row.get("impliedVolatility", None)
                if chain_iv and chain_iv > 0 and not (isinstance(chain_iv, float) and math.isnan(chain_iv)):
                    sigma = float(chain_iv)
                    iv_source = "yfinance_market"
                else:
                    sigma = hv_fallback
                    iv_source = "hv_fallback"
                greeks = bs_greeks(price, strike, T, RISK_FREE_RATE, sigma, q=q)
                if bid > 0 and ask > 0:
                    option_price = (bid + ask) / 2.0
                    price_source = "yfinance_mid"
                elif last > 0:
                    option_price = last
                    price_source = "yfinance_last"
                else:
                    option_price = greeks["price"]
                    price_source = "bs_model"
                theta = float(greeks["theta"])
                gamma = float(greeks["gamma"])
                out.append({
                    "strike": round(strike, 2), "expiry": expiry, "dte": dte,
                    "bid": round(bid, 2), "ask": round(ask, 2), "last_price": round(last, 2),
                    "option_price": round(option_price, 4), "price_source": price_source,
                    "quote_stale": bid <= 0 or ask <= 0,
                    "volume": volume, "open_interest": oi, "oi_source": "yfinance",
                    "iv": round(float(sigma), 4), "iv_source": iv_source,
                    "delta": round(float(greeks["delta"]), 4), "gamma": round(gamma, 4), "theta": round(theta, 6),
                    "gamma_theta_ratio": round(gamma / abs(theta), 4) if abs(theta) > 1e-8 else 0,
                    "premium_dollars": round(option_price * 100, 2),
                    "spread_pct": round((ask - bid) / ((ask + bid) / 2), 4) if (ask + bid) > 0 else 1.0,
                    "theta_ratio": round(abs(theta) / option_price, 4) if option_price > 0 else 999,
                    "data_provider": "yfinance",
                })
            time.sleep(YF_SLEEP)
        _record_health("yfinance", symbol, "option_chain", bool(out), f"contracts={len(out)}")
        return out
    except Exception as e:
        _record_health("yfinance", symbol, "option_chain", False, str(e))
        return []


def get_option_chain(symbol: str, price: float, hv_fallback: float, q: float = 0.0) -> Tuple[List[dict], str]:
    for provider in OPTION_PROVIDER_ORDER:
        if provider == "alpaca":
            opts = fetch_alpaca_option_chain(symbol, price)
        elif provider == "yfinance":
            opts = fetch_yfinance_option_chain(symbol, price, hv_fallback, q=q)
        else:
            continue
        if opts:
            return opts, provider
    return [], "none"


# ======================== Metrics and filters ========================
def calculate_hv(prices: np.ndarray, window: int = 21) -> float:
    if len(prices) < window:
        return 0.30
    x = np.asarray(prices[-window:], dtype=float)
    x = x[x > 0]
    if len(x) < window:
        return 0.30
    log_returns = np.diff(np.log(x))
    return float(np.std(log_returns) * np.sqrt(252))


def _hv_rank(closes: np.ndarray, window: int) -> Tuple[float, float]:
    cur_hv = calculate_hv(closes, window)
    if len(closes) < window * 3:
        return cur_hv, 0.5
    log_ret = np.diff(np.log(closes))
    rolling = np.array([np.std(log_ret[i - window + 1:i + 1]) * np.sqrt(252) for i in range(window - 1, len(log_ret))])
    if len(rolling) < 10:
        return cur_hv, 0.5
    return cur_hv, float((rolling < cur_hv).mean())


def _theta_ratio_cap(dte: int) -> float:
    if dte <= 14:
        return THETA_RATIO_SHORT
    if dte <= 30:
        return THETA_RATIO_MID
    return THETA_RATIO_LONG


def _dte_bucket(dte: int) -> str:
    if dte <= 14:
        return "short"
    if dte <= 30:
        return "mid"
    return "long"


def _percentile(values: List[float]) -> Dict[int, float]:
    if not values:
        return {}
    if len(values) == 1:
        return {0: 0.5}
    order = sorted(values)
    out: Dict[int, float] = {}
    for i, v in enumerate(values):
        lo = int(np.searchsorted(order, v, side="left"))
        hi = int(np.searchsorted(order, v, side="right"))
        avg_rank = (lo + hi - 1) / 2
        out[i] = (avg_rank + 0.5) / len(values)
    return out


def _gtr_bucketed_percentile(passing: List[dict]) -> Dict[int, float]:
    buckets: Dict[str, List[Tuple[int, float]]] = {}
    for i, p in enumerate(passing):
        buckets.setdefault(_dte_bucket(p["opt"]["dte"]), []).append((i, p["opt"].get("gamma_theta_ratio", 0)))
    out: Dict[int, float] = {}
    for _, pairs in buckets.items():
        local = _percentile([v for _, v in pairs])
        for li, (gi, _) in enumerate(pairs):
            out[gi] = local.get(li, 0.5)
    return out


def _reason_counts(filtered: list) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in filtered:
        for r in item.get("reasons", []):
            key = r.split("=")[0]
            counts[key] = counts.get(key, 0) + 1
    return counts


def _append_iv_history(snapshots: Dict[str, float]) -> None:
    try:
        with open(IV_HISTORY_PATH, "r") as f:
            hist = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        hist = {}
    today = dt.datetime.now(EST).strftime("%Y-%m-%d")
    day = hist.get(today, {})
    day.update(snapshots)
    hist[today] = day
    if len(hist) > 250:
        for k in sorted(hist.keys())[:-250]:
            del hist[k]
    _atomic_write(IV_HISTORY_PATH, hist)


# ======================== Optional slow fields ========================
# R5.4.1: _get_dividend_yield stub removed (always returned 0). Reintroduce only with a
# clean fundamental provider; until then bs_greeks is called with q=0 explicitly.


def analyze_sentiment(symbol: str, headlines: str) -> float:
    """Dormant in R5.4.1: not wired into scoring (sentiment_score removed as dead weight).
    Kept as the hook for when a clean headlines source exists."""
    if not GEMINI_API_KEY or not headlines:
        return 0.5
    prompt = (
        f"You are a quant analyst. Given these recent headlines for {symbol}:\n{headlines}\n\n"
        "Rate the short-term bullish catalyst strength from 0 (very bearish) to 1 (very bullish). "
        "Respond with only a single float number between 0 and 1."
    )
    try:
        resp = SESSION.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_API_KEY},  # R5.4.1: key out of URL (was leaking into logs/proxies)
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2, "maxOutputTokens": 10}},
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            match = re.search(r"(\d+\.?\d*)", text)
            if match:
                val = float(match.group(1))
                if 1.0 < val <= 10.0:
                    val /= 10.0
                elif val > 10.0:
                    return 0.5
                return max(0.0, min(1.0, val))
    except Exception as e:
        logger.debug(f"Gemini API failed {symbol}: {e}")
    return 0.5


# ======================== Universe ========================
def get_pool_universe() -> pd.DataFrame:
    rows = [{"symbol": s, "name": s, "sector": "Pool", "industry": ""} for s in POOL_SYMBOLS]
    df = pd.DataFrame(rows)
    logger.info(f"Pool universe: {len(df)} symbols: {', '.join(POOL_SYMBOLS)}")
    return df


def get_sp500_universe() -> pd.DataFrame:
    try:
        tables = pd.read_html(SP500_URL)
        df = tables[0].copy().rename(columns={"Symbol": "symbol", "Security": "name", "GICS Sector": "sector", "GICS Sub-Industry": "industry"})
        df = df[[c for c in ["symbol", "name", "sector", "industry"] if c in df.columns]].dropna(subset=["symbol"])
        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
        if SCAN_MAX_SYMBOLS > 0:
            df = df.head(SCAN_MAX_SYMBOLS)
        logger.info(f"S&P 500 universe: {len(df)} symbols")
        return df
    except Exception as e:
        logger.error(f"S&P 500 加载失败: {e}")
        return pd.DataFrame(columns=["symbol", "name", "sector", "industry"])


# ======================== Earnings ========================
def _load_earnings_cache() -> dict:
    try:
        with open(EARNINGS_CACHE_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_earnings_cache(cache: dict) -> None:
    _atomic_write(EARNINGS_CACHE_PATH, cache)


def _fetch_next_earnings_date(symbol: str) -> Optional[str]:
    # Keep yfinance as non-critical enrichment only. If it fails, scanner remains usable.
    if yf is None:
        return None
    try:
        ticker = yf.Ticker(normalize_symbol_for_yf(symbol))
        cal = ticker.calendar
        today = dt.date.today()
        if cal is None:
            return None
        if isinstance(cal, pd.DataFrame):
            if cal.empty:
                return None
            if "Earnings Date" in cal.columns:
                dates = cal["Earnings Date"].tolist()
            elif "Earnings Date" in cal.index:
                dates = cal.loc["Earnings Date"].tolist()
            else:
                return None
        elif isinstance(cal, dict):
            dates = cal.get("Earnings Date", [])
        else:
            return None
        if not isinstance(dates, list):
            dates = [dates]
        for x in dates:
            if hasattr(x, "date"):
                d = x.date()
            elif isinstance(x, str):
                d = dt.datetime.strptime(x[:10], "%Y-%m-%d").date()
            else:
                continue
            if (d - today).days >= 0:
                return d.isoformat()
    except Exception:
        return None
    return None


def get_earnings_proximity(symbol: str, cache: dict) -> Optional[int]:
    today = dt.date.today()
    ent = cache.get(symbol)
    if ent:
        try:
            checked = dt.date.fromisoformat(ent["checked"])
            fresh = (today - checked).days < EARNINGS_CACHE_DAYS
            next_str = ent.get("next")
            if fresh:
                if next_str:
                    days = (dt.date.fromisoformat(next_str) - today).days
                    return days if days >= 0 else None
                return None
        except (ValueError, KeyError):
            pass
    next_str = _fetch_next_earnings_date(symbol)
    cache[symbol] = {"checked": today.isoformat(), "next": next_str}
    return (dt.date.fromisoformat(next_str) - today).days if next_str else None


# ======================== Stage 1 / 2 / 3 ========================
def _batch_price_metrics(symbols: List[str]) -> Optional[pd.DataFrame]:
    rows = []
    for sym in symbols:
        hist, provider = get_stock_history(sym)
        if hist is None or len(hist) < 5:
            continue
        price, price_source = get_latest_price(sym, hist, provider)
        stat = hist.tail(5).copy()
        dollar_vol = float((stat["Volume"] * stat["Close"]).mean())
        abs_ret_5d = abs(float(price / stat["Close"].iloc[0] - 1))
        range_pct = float(((stat["High"] - stat["Low"]) / stat["Close"]).mean())
        rows.append({"symbol": sym, "price": price, "dollar_vol": dollar_vol, "abs_ret_5d": abs_ret_5d, "range_pct": range_pct, "data_provider": provider, "price_source": price_source})
    if not rows:
        return None
    logger.info(f"Stage 1 data coverage: {len(rows)}/{len(symbols)}")
    return pd.DataFrame(rows)


def stage1_static_filter(universe_df: pd.DataFrame, perilla_symbols: set, fda_map: dict) -> pd.DataFrame:
    logger.info("=== Stage 1: data-provider static filter ===")
    df = universe_df.copy()
    df["is_perilla"] = df["symbol"].isin(perilla_symbols)
    df["has_fda"] = df["symbol"].isin(fda_map.keys())
    priority = df[df["is_perilla"] | df["has_fda"]].copy()
    priority["stage1_reason"] = "catalyst_priority"
    rest = df[~(df["is_perilla"] | df["has_fda"])].copy()
    slots = max(0, BFS_STAGE1_KEEP - len(priority))
    metrics = _batch_price_metrics(rest["symbol"].tolist()) if slots > 0 else pd.DataFrame()
    if metrics is None or metrics.empty:
        logger.warning("Stage 1 metrics empty; using date-rotating sample fallback")
        seed = int(dt.date.today().strftime("%Y%m%d"))
        sampled = rest.sample(min(len(rest), slots), random_state=seed).copy() if slots else pd.DataFrame(columns=df.columns)
        sampled["stage1_reason"] = "fallback_rotating_sample"
    else:
        merged = rest.merge(metrics, on="symbol", how="inner")
        merged = merged[(merged["price"] >= SCAN_MIN_PRICE) & (merged["price"] <= SCAN_MAX_PRICE) & (merged["dollar_vol"] >= STAGE1_MIN_DOLLAR_VOL)].copy()
        merged["activity"] = merged["abs_ret_5d"] + merged["range_pct"]
        merged = merged.sort_values("activity", ascending=False)
        picked, counts = [], {}
        sector_cap = max(5, slots // max(1, STAGE1_SECTOR_CAP_DIV))
        for _, r in merged.iterrows():
            sec = r.get("sector") or "Unknown"
            if counts.get(sec, 0) >= sector_cap:
                continue
            picked.append(r)
            counts[sec] = counts.get(sec, 0) + 1
            if len(picked) >= slots:
                break
        sampled = pd.DataFrame(picked) if picked else pd.DataFrame(columns=merged.columns)
        sampled["stage1_reason"] = "activity_rank"
    result = pd.concat([priority, sampled], ignore_index=True)
    logger.info(f"Stage 1 pass: {len(result)}")
    return result


def get_stock_data_light(symbol: str) -> Optional[dict]:
    hist, provider = get_stock_history(symbol)
    if hist is None or hist.empty or len(hist) < 30:
        return None
    price, price_source = get_latest_price(symbol, hist, provider)
    closes = hist["Close"].astype(float).values
    hv, hv_rank = _hv_rank(closes, HV_RANK_WINDOW)
    recent = hist.tail(5)
    avg_volume = float(recent["Volume"].mean()) if "Volume" in recent else 0.0
    dollar_vol = float((recent["Volume"] * recent["Close"]).mean()) if "Volume" in recent else 0.0
    return {
        "symbol": symbol,
        "price": float(price),
        "price_source": price_source,
        "data_provider": provider,
        "avg_volume": avg_volume,
        "dollar_vol": dollar_vol,
        "liquidity_proxy": min(dollar_vol / 1_000_000_000.0, 1.0),
        "hv": round(float(hv), 4),
        "hv_rank": round(float(hv_rank), 3),
    }


def stage2_light_data(
    stage1_df: pd.DataFrame,
    perilla_symbols: set,
    fda_map: dict,
    max_keep: Optional[int] = None,
) -> List[dict]:
    logger.info("=== Stage 2: light data with provider router ===")
    results = []
    fetch_fail = 0
    earnings_cache = _load_earnings_cache()
    for _, row in stage1_df.iterrows():
        symbol = str(row["symbol"]).upper()
        is_perilla = bool(row.get("is_perilla", False))
        is_catalyst = is_perilla or symbol in fda_map
        data = get_stock_data_light(symbol)
        if not data:
            fetch_fail += 1
            if is_catalyst:
                logger.warning(f"催化剂标的 Stage 2 数据失败: {symbol}")
            continue
        price = data["price"]
        is_pool = symbol in POOL_SYMBOLS
        if (price < SCAN_MIN_PRICE or price > SCAN_MAX_PRICE) and not (is_pool or is_perilla):
            continue
        earnings_days = get_earnings_proximity(symbol, earnings_cache)
        has_earnings_catalyst = earnings_days is not None and EARNINGS_WINDOW_MIN <= earnings_days <= EARNINGS_WINDOW_MAX
        results.append({
            "symbol": symbol,
            "name": row.get("name", symbol),
            "sector": row.get("sector", ""),
            "price": price,
            "price_source": data["price_source"],
            "data_provider": data["data_provider"],
            "avg_volume": data["avg_volume"],
            "dollar_vol": data["dollar_vol"],
            "liquidity_proxy": data["liquidity_proxy"],
            "hv": data["hv"],
            "hv_rank": data["hv_rank"],
            "is_perilla": is_perilla,
            "has_fda": symbol in fda_map,
            "fda_info": fda_map.get(symbol),
            "has_earnings_catalyst": has_earnings_catalyst,
            "earnings_days": earnings_days,
        })
    _save_earnings_cache(earnings_cache)
    results.sort(key=lambda x: (-(3 * x["is_perilla"] + 2 * x["has_fda"] + 1 * x["has_earnings_catalyst"]), -x["liquidity_proxy"]))
    keep = max_keep if max_keep is not None else BFS_STAGE2_KEEP
    out = results[:keep]
    logger.info(f"Stage 2 pass: {len(out)} | fetch_fail: {fetch_fail}")
    return out


def stage3_full_analysis(stage2_results: List[dict], watchlist: dict) -> List[dict]:
    logger.info("=== Stage 3: options analysis + score ===")
    perilla_boost = float(watchlist.get("perilla_score_boost", 15))
    fda_boost = float(watchlist.get("fda_score_boost", 12))
    passing: List[dict] = []
    filtered_log: List[dict] = []
    fetch_fail = 0
    iv_snapshots: Dict[str, float] = {}

    for item in stage2_results:
        symbol = item["symbol"]
        # R5.4.1: dividend-yield stub always returned 0; pass q=0 explicitly until a clean
        # fundamental provider exists. Sentiment likewise removed from scoring (was a dead +5 constant).
        options, option_provider = get_option_chain(symbol, item["price"], item["hv"], q=0.0)
        if not options:
            fetch_fail += 1
            if item.get("is_perilla") or item.get("has_fda"):
                logger.warning(f"催化剂标的 Stage 3 期权数据全失败: {symbol}")
            continue
        market_ivs = [o["iv"] for o in options if o.get("iv") and "fallback" not in o.get("iv_source", "")]
        if market_ivs:
            iv_snapshots[symbol] = round(float(np.median(market_ivs)), 4)

        for opt in options:
            reasons = []
            if opt["quote_stale"]:
                reasons.append("stale_quote")
            if not (MIN_DELTA <= opt["delta"] <= MAX_DELTA):
                reasons.append(f"delta={opt['delta']}")
            if opt["gamma"] < MIN_GAMMA:
                reasons.append(f"gamma={opt['gamma']}")
            if opt["theta_ratio"] > _theta_ratio_cap(opt["dte"]):
                reasons.append(f"theta_ratio={opt['theta_ratio']}(cap={_theta_ratio_cap(opt['dte'])}@{opt['dte']}d)")
            if opt["iv"] > MAX_IV:
                reasons.append(f"iv={opt['iv']}")
            if opt["spread_pct"] > MAX_SPREAD_PCT:
                reasons.append(f"spread={opt['spread_pct']:.2%}")
            # R5.4: when OI is unavailable from free snapshot, do not kill all Alpaca candidates.
            if opt.get("oi_source") == "missing_in_snapshot":
                if opt["volume"] < MIN_VOLUME:
                    reasons.append(f"vol={opt['volume']}/oi=NA")
            else:
                if opt["volume"] < MIN_VOLUME and opt["open_interest"] < MIN_OPEN_INTEREST:
                    reasons.append(f"vol={opt['volume']}/oi={opt['open_interest']}")
            if opt["premium_dollars"] > CAPITAL_PER_TRADE:
                reasons.append(f"premium=${opt['premium_dollars']}")
            if reasons:
                if LOGGING_FIRST:
                    filtered_log.append({"symbol": symbol, "strike": opt["strike"], "expiry": opt["expiry"], "reasons": reasons, "provider": opt.get("data_provider")})
                continue
            passing.append({"opt": opt, "item": item, "option_provider": option_provider})

    gtr_pct = _gtr_bucketed_percentile(passing)
    scored: List[dict] = []
    for i, p in enumerate(passing):
        opt, item = p["opt"], p["item"]
        # Liquidity: volume + OI when available + underlying dollar-liquidity proxy.
        oi_component = min(opt.get("open_interest", 0) / 500, 1.0) if opt.get("oi_source") != "missing_in_snapshot" else 0.35
        liquidity_raw = min(opt["volume"] / 300, 1.0) * 0.40 + oi_component * 0.25 + item.get("liquidity_proxy", 0) * 0.35
        liquidity_score = liquidity_raw * 25
        spread_score = max(0, 1 - opt["spread_pct"] / MAX_SPREAD_PCT) * 15
        delta_score = max(0, 1 - abs(opt["delta"] - 0.38) / 0.15) * 15
        gtr_score = gtr_pct.get(i, 0.5) * 15
        hv_rank = item.get("hv_rank", 0.5)
        iv_hv = (opt["iv"] / item["hv"]) if item.get("hv", 0) > 0 else 1.5
        iv_hv_score = max(0.0, min(1.0, (1.8 - iv_hv) / 1.0))
        iv_value_score = (0.5 * (1 - hv_rank) + 0.5 * iv_hv_score) * IV_VALUE_WEIGHT
        catalyst_score = 0.0
        if item["has_earnings_catalyst"]:
            catalyst_score += EARNINGS_SCORE_BOOST
        if item["has_fda"]:
            catalyst_score += fda_boost
        if item["is_perilla"]:
            catalyst_score += perilla_boost
        total = round(float(liquidity_score + spread_score + delta_score + gtr_score + iv_value_score + catalyst_score), 2)
        scored.append({
            **opt,
            "symbol": item["symbol"], "name": item["name"], "sector": item["sector"],
            "underlying_price": round(item["price"], 2),
            "underlying_price_source": item.get("price_source"),
            "stock_data_provider": item.get("data_provider"),
            "option_data_provider": opt.get("data_provider"),
            "dollar_vol_M": round(item.get("dollar_vol", 0) / 1e6, 1),
            "hv_rank": round(hv_rank, 3), "iv_hv_ratio": round(iv_hv, 3),
            "is_perilla": item["is_perilla"], "has_fda": item["has_fda"],
            "has_earnings_catalyst": item["has_earnings_catalyst"], "earnings_days": item["earnings_days"],
            "score": total,
            "score_breakdown": {
                "liquidity": round(float(liquidity_score), 1), "spread": round(float(spread_score), 1),
                "delta": round(float(delta_score), 1), "gamma_theta": round(float(gtr_score), 1),
                "iv_value": round(float(iv_value_score), 1),
                "catalyst": round(float(catalyst_score), 1),
            },
            "scan_time": dt.datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S ET"),
        })

    best_by_symbol: Dict[str, dict] = {}
    for c in scored:
        if c["symbol"] not in best_by_symbol or c["score"] > best_by_symbol[c["symbol"]]["score"]:
            best_by_symbol[c["symbol"]] = c
    top = sorted(best_by_symbol.values(), key=lambda x: x["score"], reverse=True)[:TOP_CANDIDATES]

    if filtered_log:
        _save_filtered_log(filtered_log)
    if iv_snapshots:
        _append_iv_history(iv_snapshots)
    global LAST_REASON_COUNTS
    LAST_REASON_COUNTS = _reason_counts(filtered_log)
    _atomic_write(DATA_HEALTH_PATH, DATA_HEALTH[-500:])

    logger.info(f"Stage 3 done: passing={len(passing)} filtered={len(filtered_log)} fetch_fail={fetch_fail} top={len(top)}")
    for c in top:
        logger.info(f" {c['symbol']}: score={c['score']} provider={c['stock_data_provider']}/{c['option_data_provider']} Δ={c['delta']} IV={c['iv']} spread={c['spread_pct']:.2%}")
    return top


# ======================== IO / output ========================
def _save_filtered_log(filtered: list) -> None:
    filepath = os.path.join(STATE_DIR, "filtered_candidates.json")
    try:
        with open(filepath, "r") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []
    existing.append({"time": dt.datetime.now(EST).isoformat(), "count": len(filtered), "reason_counts": _reason_counts(filtered), "samples": filtered[:30]})
    _atomic_write(filepath, existing[-60:])


def save_signals(candidates: List[dict], scan_mode: str = "sp500") -> None:
    scan_time = dt.datetime.now(EST).isoformat()
    for c in candidates:
        c["scan_mode"] = scan_mode
    filepath = os.path.join(STATE_DIR, "signals.json")
    try:
        with open(filepath, "r") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []
    existing.append({
        "scan_time": scan_time,
        "scan_mode": scan_mode,
        "candidates": candidates,
        "top_pick": candidates[0]["symbol"] if candidates else None,
    })
    _atomic_write(filepath, existing[-MAX_SIGNAL_ROUNDS:])
    export_dryrun_candidates_to_ib(candidates, scan_time, scan_mode)


def save_pool_signals(candidates: List[dict]) -> None:
    filepath = os.path.join(STATE_DIR, "pool_signals.json")
    try:
        with open(filepath, "r") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []
    scan_time = dt.datetime.now(EST).isoformat()
    for c in candidates:
        c["scan_mode"] = "pool"
    existing.append({
        "scan_time": scan_time,
        "scan_mode": "pool",
        "pool_symbols": POOL_SYMBOLS,
        "candidates": candidates,
        "top_pick": candidates[0]["symbol"] if candidates else None,
    })
    _atomic_write(filepath, existing[-MAX_SIGNAL_ROUNDS:])


def save_perilla_signals(candidates: List[dict], failed: List[str], buy_signals: List[dict]) -> None:
    payload = {
        "scan_time": dt.datetime.now(EST).isoformat(),
        "candidates": candidates,
        "buy_signals": buy_signals,
        "failed_symbols": failed,
        "buy_score_min": WATCHLIST_BUY_SCORE_MIN,
    }
    _atomic_write(os.path.join(STATE_DIR, "perilla_signals.json"), payload)


def safe_read_perilla_signals() -> dict:
    try:
        with open(os.path.join(STATE_DIR, "perilla_signals.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram 未配置")
        return
    # R5.4.1: plain Bot API call, telebot dependency dropped
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for i in range(0, len(message), 3900):
        try:
            r = SESSION.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message[i:i + 3900]}, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                logger.error(f"Telegram 发送失败: HTTP {r.status_code} {r.text[:120]}")
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Telegram 发送失败: {e}")
            break


def format_message(candidates: List[dict], label: str = "BFS Scan") -> str:
    if not candidates:
        msg = f"Aether Nexus {AETHER_VERSION}: {label} — 本轮无候选通过过滤\n"
        if LAST_REASON_COUNTS:
            msg += "\n过滤原因分布:\n" + "".join(f" {k}: {v}\n" for k, v in sorted(LAST_REASON_COUNTS.items(), key=lambda x: -x[1]))
        else:
            msg += "（可能是数据源层失败，查看 dryrun_state/data_health.json 和 dryrun.log）"
        return msg
    now = dt.datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S ET")
    msg = f"Aether Nexus {AETHER_VERSION} {label} ({now})\n\n"
    medals = ["1", "2", "3"]
    for i, c in enumerate(candidates, 1):
        label_m = medals[i - 1] if i <= 3 else "•"
        tags = []
        if c.get("is_perilla"):
            tags.append("紫苏叶")
        if c.get("has_earnings_catalyst"):
            tags.append(f"财报{c['earnings_days']}天")
        if c.get("has_fda"):
            tags.append("FDA")
        sb = c.get("score_breakdown", {})
        msg += (
            f"{label_m}. {c['symbol']} — Score {c['score']} {' '.join(tags)}\n"
            f" Underlying ${c['underlying_price']} ({c.get('underlying_price_source')}) | Call {c['strike']} | {c['expiry']} ({c['dte']}d)\n"
            f" Δ={c['delta']} Γ/Θ={c['gamma_theta_ratio']} IV={c['iv']}({c['iv_source']}) HVrank={c.get('hv_rank')} IV/HV={c.get('iv_hv_ratio')}\n"
            f" Bid/Ask ${c['bid']}/${c['ask']} | Vol {c['volume']} OI {c.get('open_interest','NA')} | Spread {c['spread_pct']:.2%}\n"
            f" Premium ${c['premium_dollars']} ({c['price_source']}) | Data {c.get('stock_data_provider')}/{c.get('option_data_provider')}\n"
            f" Score: L{sb.get('liquidity',0)} S{sb.get('spread',0)} D{sb.get('delta',0)} G{sb.get('gamma_theta',0)} V{sb.get('iv_value',0)} C{sb.get('catalyst',0)}\n\n"
        )
    msg += "---\nDry-run signal only | No order execution"
    return msg


def format_pool_message(candidates: List[dict]) -> str:
    if not candidates:
        return (
            f"Aether Nexus {AETHER_VERSION}: Pool Scan — no candidates passed filters\n"
            f"Pool: {', '.join(POOL_SYMBOLS)}"
        )
    now = dt.datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S ET")
    msg = f"Aether Nexus {AETHER_VERSION} Pool Scan ({now})\n"
    msg += f"做T池 ({len(POOL_SYMBOLS)}): {', '.join(POOL_SYMBOLS)}\n\n"
    for i, c in enumerate(candidates, 1):
        medal = ["1", "2", "3"][i - 1] if i <= 3 else "•"
        sb = c.get("score_breakdown", {})
        msg += (
            f"{medal}. {c['symbol']} — Score {c['score']}\n"
            f" ${c['underlying_price']} | Call {c['strike']} | {c['expiry']} ({c['dte']}d)\n"
            f" Δ={c['delta']} Γ/Θ={c['gamma_theta_ratio']} IV={c['iv']}({c['iv_source']})\n"
            f" Bid/Ask ${c['bid']}/${c['ask']} | Premium ${c['premium_dollars']} ({c.get('price_source', '?')})\n"
            f" Data {c.get('stock_data_provider')}/{c.get('option_data_provider')}\n"
            f" Score: L{sb.get('liquidity', 0)} S{sb.get('spread', 0)} "
            f"D{sb.get('delta', 0)} G{sb.get('gamma_theta', 0)} V{sb.get('iv_value', 0)}\n\n"
        )
    msg += "---\nDry-run pool scan | No order execution"
    return msg


def _format_candidate_block(c: dict, medal: str = "•") -> str:
    tags = []
    if c.get("is_perilla"):
        tags.append("紫苏叶")
    if c.get("has_earnings_catalyst"):
        tags.append(f"财报{c['earnings_days']}天")
    if c.get("has_fda"):
        tags.append("FDA")
    sb = c.get("score_breakdown", {})
    return (
        f"{medal} {c['symbol']} — Score {c['score']} {' '.join(tags)}\n"
        f" ${c['underlying_price']} | Call {c['strike']} | {c['expiry']} ({c['dte']}d)\n"
        f" Δ={c['delta']} Γ/Θ={c['gamma_theta_ratio']} IV={c['iv']} | Premium ${c['premium_dollars']}\n"
        f" Score: L{sb.get('liquidity', 0)} S{sb.get('spread', 0)} D{sb.get('delta', 0)} "
        f"G{sb.get('gamma_theta', 0)} V{sb.get('iv_value', 0)} C{sb.get('catalyst', 0)}\n"
    )


def format_perilla_message(candidates: List[dict], failed: List[str], watchlist: dict) -> str:
    now = dt.datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S ET")
    total = len(watchlist.get("perilla_leaf", []))
    msg = f"Aether {AETHER_VERSION} 紫苏叶 Scan ({now})\n"
    msg += f"Watchlist {total} 只 | 通过 {len(candidates)} | 数据失败 {len(failed)}\n\n"
    if candidates:
        msg += "扫描结果\n"
        for i, c in enumerate(sorted(candidates, key=lambda x: -x["score"]), 1):
            medal = ["1", "2", "3"][i - 1] if i <= 3 else "•"
            msg += _format_candidate_block(c, medal) + "\n"
    else:
        msg += "本轮无标的通过期权过滤\n\n"
    if failed:
        msg += "未拉到数据 / Stage2 失败:\n"
        msg += ", ".join(failed) + "\n"
    msg += "---\nDry-run watchlist scan"
    return msg


def format_buy_signal_reminder(buy_signals: List[dict], label: str = "买入信号") -> str:
    now = dt.datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S ET")
    msg = f"{label} ({now})\n"
    msg += f"Score >= {WATCHLIST_BUY_SCORE_MIN} | {len(buy_signals)} 只 watchlist 候选\n\n"
    for i, c in enumerate(sorted(buy_signals, key=lambda x: -x["score"]), 1):
        medal = ["1", "2", "3"][i - 1] if i <= 3 else "•"
        msg += _format_candidate_block(c, medal) + "\n"
    msg += "---\n模拟信号，非 IB 下单。请自行核实后再交易。"
    return msg


# ======================== Main scan ========================
_TRADING_DAY_CACHE: Dict[str, bool] = {}


def is_trading_day(d: Optional[dt.date] = None) -> bool:
    """R5.4.1: weekend gate always; Alpaca /v2/calendar holiday check when keys present."""
    d = d or dt.datetime.now(EST).date()
    if d.weekday() >= 5:
        return False
    key = d.isoformat()
    if key in _TRADING_DAY_CACHE:
        return _TRADING_DAY_CACHE[key]
    headers = _alpaca_headers()
    result = True  # default open on weekdays if calendar unavailable
    if headers:
        data = _request_json(f"{ALPACA_TRADING_BASE}/v2/calendar", headers=headers,
                             params={"start": key, "end": key}, provider="alpaca", endpoint="calendar")
        if data is not None:
            result = any(entry.get("date") == key for entry in (data if isinstance(data, list) else []))
    _TRADING_DAY_CACHE[key] = result
    if not result:
        logger.info(f"{key} 非交易日，跳过扫描")
    return result


def build_pool_stage1(perilla_symbols: set, fda_map: dict) -> pd.DataFrame:
    rows = []
    seen = set()
    for sym in POOL_SYMBOLS:
        rows.append({
            "symbol": sym,
            "name": sym,
            "sector": "Pool",
            "is_perilla": sym in perilla_symbols,
            "has_fda": sym in fda_map,
            "is_pool": True,
            "stage1_reason": "pool_direct",
        })
        seen.add(sym)
    for sym in perilla_symbols | set(fda_map.keys()):
        if sym in seen:
            continue
        rows.append({
            "symbol": sym,
            "name": f"[catalyst] {sym}",
            "sector": "Watchlist",
            "is_perilla": sym in perilla_symbols,
            "has_fda": sym in fda_map,
            "is_pool": False,
            "stage1_reason": "catalyst_priority",
        })
    logger.info("Pool Stage 1: %d symbols (%d pool)", len(rows), len(POOL_SYMBOLS))
    return pd.DataFrame(rows)


def run_pool_scan() -> List[dict]:
    start = time.time()
    logger.info("=" * 60)
    logger.info("Pool scan starting (%s) — %d symbols", AETHER_VERSION, len(POOL_SYMBOLS))
    watchlist = load_watchlist()
    perilla_symbols = get_perilla_symbols(watchlist)
    fda_map = get_fda_catalyst_map(watchlist)
    stage1 = build_pool_stage1(perilla_symbols, fda_map)
    stage2 = stage2_light_data(stage1, perilla_symbols, fda_map, max_keep=max(len(stage1), 999))
    if not stage2:
        logger.warning("Pool scan: Stage 2 empty")
        verify_perilla_data_sources(watchlist)
        return []
    top = stage3_full_analysis(stage2, watchlist)
    verify_perilla_data_sources(load_watchlist())
    logger.info("Pool scan finished in %.1fs", time.time() - start)
    return top


def run_sp500_scan() -> List[dict]:
    start = time.time()
    logger.info("=" * 60)
    logger.info("BFS sp500 scan starting (%s)", AETHER_VERSION)
    watchlist = load_watchlist()
    perilla_symbols = get_perilla_symbols(watchlist)
    fda_map = get_fda_catalyst_map(watchlist)
    universe = get_sp500_universe()
    if universe.empty:
        logger.error("SP500 universe empty; scan aborted")
        return []
    existing_symbols = set(universe["symbol"].tolist())
    extras = [
        {"symbol": s, "name": f"[紫苏叶] {s}", "sector": "Watchlist", "industry": ""}
        for s in perilla_symbols
        if s not in existing_symbols
    ]
    if extras:
        universe = pd.concat([universe, pd.DataFrame(extras)], ignore_index=True)
    stage1 = stage1_static_filter(universe, perilla_symbols, fda_map)
    stage2 = stage2_light_data(stage1, perilla_symbols, fda_map)
    if not stage2:
        logger.warning("BFS scan: Stage 2 empty")
        verify_perilla_data_sources(watchlist)
        return []
    top = stage3_full_analysis(stage2, watchlist)
    verify_perilla_data_sources(load_watchlist())
    logger.info("BFS sp500 scan finished in %.1fs", time.time() - start)
    return top


def run_full_scan() -> List[dict]:
    if SCAN_MODE == "sp500":
        return run_sp500_scan()
    return run_pool_scan()


def run_perilla_scan() -> Tuple[List[dict], List[str], dict]:
    start = time.time()
    logger.info("=" * 60)
    logger.info("Perilla watchlist scan starting")
    watchlist = load_watchlist()
    perilla_symbols = get_perilla_symbols(watchlist)
    fda_map = get_fda_catalyst_map(watchlist)
    if not perilla_symbols:
        logger.warning("Perilla watchlist empty")
        return [], [], watchlist
    rows = []
    for item in watchlist.get("perilla_leaf", []):
        sym = item["symbol"].upper()
        rows.append({
            "symbol": sym,
            "name": item.get("thesis", sym)[:60],
            "sector": item.get("sector", "Watchlist"),
            "is_perilla": True,
            "has_fda": sym in fda_map,
            "is_pool": sym in POOL_SYMBOLS_SET,
            "stage1_reason": "perilla_direct",
        })
    stage1 = pd.DataFrame(rows)
    stage2 = stage2_light_data(stage1, perilla_symbols, fda_map, max_keep=max(len(stage1), 999))
    passed = {r["symbol"] for r in stage2}
    failed = sorted(sym for sym in perilla_symbols if sym not in passed)
    if not stage2:
        verify_perilla_data_sources(watchlist)
        logger.info("Perilla scan: no symbols passed stage 2 (%.1fs)", time.time() - start)
        return [], failed, watchlist
    candidates = stage3_full_analysis(stage2, watchlist)
    verify_perilla_data_sources(load_watchlist())
    logger.info("Perilla scan done: %d/%d passed (%.1fs)", len(candidates), len(perilla_symbols), time.time() - start)
    return candidates, failed, watchlist


def daily_scan() -> None:
    if not is_trading_day():
        return
    logger.info("Scheduled BFS scan triggered (mode=%s)", SCAN_MODE)
    candidates = run_sp500_scan()
    send_telegram(format_message(candidates, label="BFS sp500 Scan"))
    save_signals(candidates, scan_mode="sp500")


def pool_daily_scan() -> None:
    if not POOL_SCAN_ENABLED or not is_trading_day():
        return
    logger.info("Scheduled pool scan triggered (%d symbols)", len(POOL_SYMBOLS))
    candidates = run_pool_scan()
    send_telegram(format_pool_message(candidates))
    save_pool_signals(candidates)


def perilla_daily_scan() -> None:
    if not is_trading_day():
        return
    logger.info("Scheduled perilla scan triggered")
    candidates, failed, watchlist = run_perilla_scan()
    send_telegram(format_perilla_message(candidates, failed, watchlist))
    buy_signals = [c for c in candidates if c.get("score", 0) >= WATCHLIST_BUY_SCORE_MIN]
    save_perilla_signals(candidates, failed, buy_signals)
    if buy_signals:
        send_telegram(format_buy_signal_reminder(buy_signals, label="Watchlist 买入信号"))


def _reminder_time(scan_time: str, minutes_before: int) -> str:
    try:
        scan_dt = dt.datetime.strptime(scan_time, "%H:%M")
        reminder_dt = scan_dt - dt.timedelta(minutes=minutes_before)
        return reminder_dt.strftime("%H:%M")
    except ValueError:
        return ""


def _send_buy_reminder(label: str) -> None:
    if not is_trading_day():
        return
    perilla_state = safe_read_perilla_signals()
    buy_signals = perilla_state.get("buy_signals", [])
    if buy_signals:
        send_telegram(format_buy_signal_reminder(buy_signals, label=label))
    else:
        send_telegram(f"今日紫苏叶 scan 暂无 score>={WATCHLIST_BUY_SCORE_MIN:.0f} 的买入信号")



def main() -> None:
    perilla_reminder = _reminder_time(PERILLA_SCAN_TIME, PERILLA_REMINDER_MIN)
    logger.info("=" * 60)
    logger.info("Aether Nexus %s — Data-Hardened Dry Run (integrated)", AETHER_VERSION)
    logger.info("Stock providers: %s", DATA_PROVIDER_ORDER)
    logger.info("Option providers: %s", OPTION_PROVIDER_ORDER)
    logger.info(
        "Alpaca configured: %s | stock_feed=%s option_feed=%s",
        "YES" if _alpaca_headers() else "NO",
        ALPACA_DATA_FEED,
        ALPACA_OPTION_FEED,
    )
    logger.info("BFS mode: %s @ %s / %s EST", SCAN_MODE.upper(), SCAN_PRE_MARKET, SCAN_POST_MARKET)
    if POOL_SCAN_ENABLED:
        logger.info("Pool scan: %s / %s EST (%d symbols)", POOL_SCAN_PRE_MARKET, POOL_SCAN_POST_MARKET, len(POOL_SYMBOLS))
    logger.info("Perilla scan: %s EST (reminder %s)", PERILLA_SCAN_TIME, perilla_reminder or "n/a")
    logger.info("Buy reminders: %s / %s EST", WATCHLIST_BUY_REMINDER, WATCHLIST_BUY_REMINDER_PM)
    logger.info("=" * 60)

    if _telegram_configured():
        startup = (
            f"Aether Nexus {AETHER_VERSION} started\n\n"
            f"BFS: {SCAN_MODE.upper()} @ {SCAN_PRE_MARKET}/{SCAN_POST_MARKET} EST\n"
        )
        if POOL_SCAN_ENABLED:
            startup += f"Pool: {len(POOL_SYMBOLS)} symbols @ {POOL_SCAN_PRE_MARKET}/{POOL_SCAN_POST_MARKET} EST\n"
        startup += (
            f"Providers: stocks={DATA_PROVIDER_ORDER}, options={OPTION_PROVIDER_ORDER}\n"
            f"Perilla: {PERILLA_SCAN_TIME} EST | Buy reminders: {WATCHLIST_BUY_REMINDER}/{WATCHLIST_BUY_REMINDER_PM} EST"
        )
        send_telegram(startup)

    if DRYRUN_SCAN_ON_START and is_trading_day():
        daily_scan()
        if POOL_SCAN_ENABLED:
            pool_daily_scan()

    last_triggered: set = set()
    while True:
        try:
            now = dt.datetime.now(EST)
            today_key = now.strftime("%Y-%m-%d")
            current_time = now.strftime("%H:%M")

            if perilla_reminder and current_time == perilla_reminder:
                key = f"{today_key}_perilla_reminder"
                if key not in last_triggered:
                    last_triggered.add(key)
                    send_telegram(f"紫苏叶 scan 将在 {PERILLA_SCAN_TIME} EST 开始（约 {PERILLA_REMINDER_MIN} 分钟后）")

            if current_time == PERILLA_SCAN_TIME:
                key = f"{today_key}_perilla_scan"
                if key not in last_triggered:
                    last_triggered.add(key)
                    perilla_daily_scan()

            for scan_time in [SCAN_PRE_MARKET, SCAN_POST_MARKET]:
                key = f"{today_key}_bfs_{scan_time}"
                if current_time == scan_time and key not in last_triggered:
                    last_triggered.add(key)
                    daily_scan()

            if POOL_SCAN_ENABLED:
                for scan_time in [POOL_SCAN_PRE_MARKET, POOL_SCAN_POST_MARKET]:
                    key = f"{today_key}_pool_{scan_time}"
                    if current_time == scan_time and key not in last_triggered:
                        last_triggered.add(key)
                        pool_daily_scan()

            for reminder_time, label, suffix in [
                (WATCHLIST_BUY_REMINDER, "开盘前买入提醒", "buy_am"),
                (WATCHLIST_BUY_REMINDER_PM, "下午买入提醒", "buy_pm"),
            ]:
                key = f"{today_key}_{suffix}"
                if current_time == reminder_time and key not in last_triggered:
                    last_triggered.add(key)
                    _send_buy_reminder(label)

            last_triggered = {k for k in last_triggered if k.startswith(today_key)}
            time.sleep(30)
        except KeyboardInterrupt:
            logger.info("Aether dry run stopped")
            break
        except Exception as e:
            logger.error("main loop error: %s", e)
            time.sleep(60)


if __name__ == "__main__":
    main()
