#!/usr/bin/env python3
"""
Aether Nexus R3.4 — Opus Audit Consolidated
- Removed unused numpy dependency (math only).
- .env AI keys commented as reserved.
- Explicit single-entry-per-cycle buy break documented.
- CLOSE_MAX_RETRIES / CLOSE_RETRY_DELAY configurable via .env.
"""
import asyncio
import datetime
import logging
import math
import os
import time
from io import StringIO
from typing import List, Optional, Tuple

import nest_asyncio
import pandas as pd
import pytz
import requests
import streamlit as st
import telebot
from dotenv import load_dotenv

# ib_insync/eventkit requires an event loop at import time (Python 3.10+ / Streamlit)
nest_asyncio.apply()
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, LimitOrder, Option, Stock

load_dotenv()

# ======================== Configuration ========================
IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "7497"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
MOCK_IB = os.getenv("MOCK_IB", "false").lower() == "true"
PAPER_PORT = 7497
LIVE_PORT = 7496

PUSHOVER_USER = os.getenv("PUSHOVER_USER", "")
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
CAPITAL_PER_TRADE = float(os.getenv("CAPITAL_PER_TRADE", "1000.0"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.2"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.5"))
TRADING_START = os.getenv("TRADING_START", "00:00" if MOCK_IB else "10:00")
TRADING_END = os.getenv("TRADING_END", "23:59" if MOCK_IB else "15:00")
FORCE_CLOSE_TIME = os.getenv("FORCE_CLOSE_TIME", "15:45")

TOP_CANDIDATES = int(os.getenv("TOP_CANDIDATES", "5"))
CLOSE_MAX_RETRIES = int(os.getenv("CLOSE_MAX_RETRIES", "3"))
CLOSE_RETRY_DELAY = float(os.getenv("CLOSE_RETRY_DELAY", "2"))

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SCAN_MAX_SYMBOLS = int(os.getenv("SCAN_MAX_SYMBOLS", "0"))
SCAN_SLEEP_SEC = float(os.getenv("SCAN_SLEEP_SEC", "0.10"))
SCAN_MIN_PRICE = float(os.getenv("SCAN_MIN_PRICE", "20"))
SCAN_MAX_PRICE = float(os.getenv("SCAN_MAX_PRICE", "1200"))
SCAN_MIN_DTE = int(os.getenv("SCAN_MIN_DTE", "7"))
SCAN_MAX_DTE = int(os.getenv("SCAN_MAX_DTE", "45"))
SCAN_TARGET_OTM = float(os.getenv("SCAN_TARGET_OTM", "1.02"))

MIN_DELTA = float(os.getenv("MIN_DELTA", "0.30"))
MAX_DELTA = float(os.getenv("MAX_DELTA", "0.45"))
MIN_GAMMA = float(os.getenv("MIN_GAMMA", "0.02"))
MAX_THETA_RATIO = float(os.getenv("MAX_THETA_RATIO", "0.05"))
MAX_IV_ABS = float(os.getenv("MAX_IV_ABS", "0.70"))
MIN_OPT_VOLUME = int(os.getenv("MIN_OPT_VOLUME", "20"))
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.05"))
ORDER_TIMEOUT = int(os.getenv("ORDER_TIMEOUT", "15"))

EST = pytz.timezone("US/Eastern")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("AetherNexus")


# ======================== Notifications ========================
def send_notification(message: str, priority: str = "normal") -> None:
    if PUSHOVER_USER and PUSHOVER_TOKEN:
        if priority == "critical":
            if _pushover(message, critical=True):
                return
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                _telegram("🚨 [CRITICAL FALLBACK]\n" + message)
                return
            logger.error("CRITICAL notification failed on all channels: %s", message[:120])
            return
        if _pushover(message):
            return
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        _telegram(message)


def _pushover(message: str, critical: bool = False) -> bool:
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        return False
    data = {"token": PUSHOVER_TOKEN, "user": PUSHOVER_USER, "message": message[:1024]}
    if critical:
        data["priority"] = 2
        data["retry"] = 60
        data["expire"] = 300
    try:
        resp = requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def _telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
        bot.send_message(TELEGRAM_CHAT_ID, message[:4096])
    except Exception:
        pass


# ======================== IB Broker ========================
class IBBroker:
    def __init__(self):
        self.ib = IB()
        self.connected = False
        self.is_live = False

    def connect(self) -> bool:
        actual_port = IB_PORT
        if LIVE_TRADING_ENABLED and actual_port != LIVE_PORT:
            logger.error(
                "LIVE_TRADING_ENABLED=true but port is %s; expected %s — refusing connection",
                actual_port,
                LIVE_PORT,
            )
            return False
        if not LIVE_TRADING_ENABLED and actual_port == LIVE_PORT:
            logger.error(
                "LIVE_TRADING_ENABLED=false but port is %s; expected %s — refusing connection",
                LIVE_PORT,
                PAPER_PORT,
            )
            return False
        self.is_live = LIVE_TRADING_ENABLED
        try:
            self.ib.connect(IB_HOST, actual_port, clientId=IB_CLIENT_ID)
            # Paper: IB default delayed feed (~15 min); sufficient for scan validation
            self.ib.reqMarketDataType(1 if self.is_live else 3)
            self.connected = True
            mode = "LIVE" if self.is_live else "PAPER"
            logger.info("IB connected: port %s / %s", actual_port, mode)
            return True
        except Exception as e:
            logger.error("IB connection failed: %s", e)
            self.connected = False
            return False

    def disconnect(self) -> None:
        if self.connected:
            try:
                self.ib.disconnect()
            except Exception as e:
                logger.error("IB disconnect error: %s", e)
            self.connected = False

    def _parse_multiplier(self, raw_multiplier) -> Optional[int]:
        if raw_multiplier in (None, "", 0, "0"):
            return None
        try:
            multiplier = int(float(raw_multiplier))
            return multiplier if multiplier > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def normalize_symbol_for_ib(symbol: str) -> str:
        return symbol.replace(".", " ").strip()

    def get_underlying_price(self, symbol: str) -> Optional[float]:
        if not self.connected:
            return None
        try:
            ib_symbol = self.normalize_symbol_for_ib(symbol)
            stock = Stock(ib_symbol, "SMART", "USD")
            self.ib.qualifyContracts(stock)
            ticker = self.ib.reqMktData(stock, "", False, False)
            self.ib.sleep(2)
            price = ticker.marketPrice()
            if not price or price <= 0:
                bid = ticker.bid if ticker.bid not in (None, -1) else 0
                ask = ticker.ask if ticker.ask not in (None, -1) else 0
                if bid > 0 and ask > 0:
                    price = (bid + ask) / 2
            self.ib.cancelMktData(stock)
            return price if price and price > 0 else None
        except Exception as e:
            logger.error("Failed to get underlying price for %s: %s", symbol, e)
            return None

    def get_option_chain(self, symbol: str) -> pd.DataFrame:
        if not self.connected:
            return pd.DataFrame()
        try:
            ib_symbol = self.normalize_symbol_for_ib(symbol)
            stock = Stock(ib_symbol, "SMART", "USD")
            details = self.ib.reqContractDetails(stock)
            if not details:
                return pd.DataFrame()
            con_id = details[0].contract.conId
            chains = self.ib.reqSecDefOptParams(ib_symbol, "", "STK", con_id)
            rows = []
            for chain in chains:
                for strike in chain.strikes:
                    for expiry in chain.expirations:
                        rows.append({"expiry": expiry, "strike": strike})
            return pd.DataFrame(rows)
        except Exception as e:
            logger.error("Failed to get option chain for %s: %s", symbol, e)
            return pd.DataFrame()

    @staticmethod
    def _safe_greek(model_greeks, attr: str, default: float = 0.0) -> float:
        if model_greeks is None:
            return default
        val = getattr(model_greeks, attr, None)
        if val is None:
            return default
        try:
            if math.isnan(val) or math.isinf(val):
                return default
        except TypeError:
            return default
        return float(val)

    def get_option_market_data(
        self, symbol: str, expiry: str, strike: float, right: str = "C"
    ) -> dict:
        if not self.connected:
            return {}
        try:
            ib_symbol = self.normalize_symbol_for_ib(symbol)
            contract = Option(ib_symbol, expiry, strike, right, "SMART", currency="USD")
            self.ib.qualifyContracts(contract)
            ticker = self.ib.reqMktData(contract, "221", False, False)
            self.ib.sleep(2)
            price = ticker.marketPrice()
            bid = ticker.bid if ticker.bid is not None and ticker.bid != -1 else 0
            ask = ticker.ask if ticker.ask is not None and ticker.ask != -1 else 0
            delta = self._safe_greek(ticker.modelGreeks, "delta")
            gamma = self._safe_greek(ticker.modelGreeks, "gamma")
            theta = self._safe_greek(ticker.modelGreeks, "theta")
            iv = self._safe_greek(ticker.modelGreeks, "impliedVol")
            volume = ticker.volume if getattr(ticker, "volume", None) not in (None, -1) else 0
            self.ib.cancelMktData(contract)
            return {
                "price": price if price and price > 0 else 0,
                "bid": bid,
                "ask": ask,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "iv": iv,
                "volume": volume or 0,
            }
        except Exception as e:
            logger.error("Failed to get option market data %s %s %s: %s", symbol, expiry, strike, e)
            return {}

    def _place_order_with_timeout(self, contract, order, timeout: int = ORDER_TIMEOUT) -> dict:
        trade = self.ib.placeOrder(contract, order)
        start = time.time()
        timed_out = False
        while not trade.isDone():
            if time.time() - start > timeout:
                timed_out = True
                self.ib.cancelOrder(order)
                for _ in range(20):
                    self.ib.sleep(0.1)
                    if trade.orderStatus and trade.orderStatus.status in (
                        "Cancelled",
                        "ApiCancelled",
                        "Filled",
                        "Inactive",
                    ):
                        break
                break
            self.ib.sleep(0.1)

        status_obj = trade.orderStatus
        filled = status_obj.filled if status_obj else 0
        remaining = status_obj.remaining if status_obj else 0
        avg_price = status_obj.avgFillPrice if status_obj and filled > 0 else 0.0
        ib_status = status_obj.status if status_obj else "UNKNOWN"
        order_id = trade.order.orderId if trade and trade.order else None

        if filled > 0:
            return {
                "status": "filled" if remaining == 0 else "partial_fill",
                "filled": filled,
                "remaining": remaining,
                "avgFillPrice": avg_price,
                "ib_status": ib_status,
                "timed_out": timed_out,
                "order_id": order_id,
            }
        if timed_out:
            return {
                "status": "timeout_cancelled",
                "filled": 0,
                "remaining": remaining,
                "avgFillPrice": 0.0,
                "ib_status": ib_status,
                "timed_out": True,
                "order_id": order_id,
                "reason": "Order timed out and cancel requested; no fill",
            }
        return {
            "status": "failed",
            "filled": filled,
            "remaining": remaining,
            "avgFillPrice": avg_price,
            "ib_status": ib_status,
            "timed_out": timed_out,
            "order_id": order_id,
            "reason": ib_status or "No fill",
        }

    def buy_call_option_limit(self, symbol: str, expiry: str, strike: float, quantity: int = 1) -> dict:
        if not self.connected:
            return {"status": "failed", "reason": "Not connected"}
        try:
            ib_symbol = self.normalize_symbol_for_ib(symbol)
            contract = Option(ib_symbol, expiry, strike, "C", "SMART", currency="USD")
            self.ib.qualifyContracts(contract)
            mkt = self.get_option_market_data(symbol, expiry, strike, "C")
            limit_price = mkt.get("ask", 0)
            if limit_price <= 0:
                return {"status": "failed", "reason": "Unable to obtain ask price"}
            order = LimitOrder("BUY", quantity, limit_price)
            return self._place_order_with_timeout(contract, order)
        except Exception as e:
            return {"status": "failed", "reason": str(e)}

    def sell_option_limit(self, symbol: str, expiry: str, strike: float, quantity: int = 1) -> dict:
        if not self.connected:
            return {"status": "failed", "reason": "Not connected"}
        try:
            ib_symbol = self.normalize_symbol_for_ib(symbol)
            contract = Option(ib_symbol, expiry, strike, "C", "SMART", currency="USD")
            self.ib.qualifyContracts(contract)
            mkt = self.get_option_market_data(symbol, expiry, strike, "C")
            limit_price = mkt.get("bid", 0)
            if limit_price <= 0:
                return {"status": "failed", "reason": "Unable to obtain bid price"}
            order = LimitOrder("SELL", quantity, limit_price)
            return self._place_order_with_timeout(contract, order)
        except Exception as e:
            return {"status": "failed", "reason": str(e)}

    def get_positions(self) -> List[dict]:
        if not self.connected:
            return []
        positions = []
        try:
            for pos in self.ib.positions():
                contract = pos.contract
                if not hasattr(contract, "right") or contract.right != "C":
                    continue
                qty = int(pos.position)
                if qty <= 0:
                    continue

                raw_multiplier = getattr(contract, "multiplier", None)
                multiplier = self._parse_multiplier(raw_multiplier)
                if multiplier is None:
                    try:
                        qualified = self.ib.qualifyContracts(contract)
                        if qualified:
                            raw_multiplier = getattr(qualified[0], "multiplier", None)
                            multiplier = self._parse_multiplier(raw_multiplier)
                    except Exception:
                        pass

                raw_avg_cost = pos.avgCost
                if multiplier is None:
                    normalized_premium = None
                    audit_status = "MULTIPLIER_MISSING_BLOCK_AUTO_RISK"
                else:
                    normalized_premium = raw_avg_cost / multiplier
                    audit_status = "OK"

                positions.append(
                    {
                        "symbol": contract.symbol,
                        "strike": contract.strike,
                        "expiry": contract.lastTradeDateOrContractMonth,
                        "quantity": qty,
                        "raw_avgCost": round(raw_avg_cost, 4),
                        "multiplier": multiplier,
                        "normalized_premium": round(normalized_premium, 4)
                        if normalized_premium is not None
                        else None,
                        "audit_status": audit_status,
                    }
                )
        except Exception as e:
            logger.error("Failed to fetch positions: %s", e)
        return positions


class MockIBBroker:
    """Simulated broker for headless testing when TWS/Gateway is unavailable."""

    def __init__(self):
        self.connected = False
        self.is_live = False
        self._positions: List[dict] = []
        self._order_id = 1000

    @staticmethod
    def _seed(symbol: str, extra: float = 0) -> int:
        return sum(ord(c) for c in symbol) + int(extra)

    def connect(self) -> bool:
        self.connected = True
        self.is_live = False
        logger.info("Mock IB connected (MOCK_IB=true)")
        return True

    def disconnect(self) -> None:
        self.connected = False

    @staticmethod
    def normalize_symbol_for_ib(symbol: str) -> str:
        return symbol.replace(".", " ").strip()

    def get_underlying_price(self, symbol: str) -> Optional[float]:
        if not self.connected:
            return None
        seed = self._seed(symbol)
        return float(30 + (seed % 900))

    def get_option_chain(self, symbol: str) -> pd.DataFrame:
        if not self.connected:
            return pd.DataFrame()
        today = datetime.datetime.now(EST).date()
        expiries = [
            (today + datetime.timedelta(days=14)).strftime("%Y%m%d"),
            (today + datetime.timedelta(days=28)).strftime("%Y%m%d"),
        ]
        price = self.get_underlying_price(symbol) or 100.0
        strikes = [round(price * m, 1) for m in (1.0, 1.02, 1.05, 1.08)]
        rows = [{"expiry": exp, "strike": s} for exp in expiries for s in strikes]
        return pd.DataFrame(rows)

    @staticmethod
    def _safe_greek(model_greeks, attr: str, default: float = 0.0) -> float:
        return IBBroker._safe_greek(model_greeks, attr, default)

    def get_option_market_data(
        self, symbol: str, expiry: str, strike: float, right: str = "C"
    ) -> dict:
        if not self.connected:
            return {}
        seed = self._seed(symbol, strike)
        delta = 0.30 + (seed % 16) / 100.0
        gamma = 0.02 + (seed % 5) / 1000.0
        option_price = 2.0 + (seed % 80) / 10.0
        bid = round(option_price * 0.98, 2)
        ask = round(option_price * 1.02, 2)
        theta = -option_price * (0.01 + (seed % 3) / 100.0)
        iv = 0.25 + (seed % 30) / 100.0
        volume = 50 + (seed % 450)
        return {
            "price": option_price,
            "bid": bid,
            "ask": ask,
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "iv": iv,
            "volume": volume,
        }

    def _place_order_with_timeout(self, contract, order, timeout: int = ORDER_TIMEOUT) -> dict:
        self._order_id += 1
        return {
            "status": "filled",
            "filled": order.totalQuantity,
            "remaining": 0,
            "avgFillPrice": order.lmtPrice,
            "ib_status": "Filled",
            "timed_out": False,
            "order_id": self._order_id,
        }

    def buy_call_option_limit(self, symbol: str, expiry: str, strike: float, quantity: int = 1) -> dict:
        if not self.connected:
            return {"status": "failed", "reason": "Not connected"}
        mkt = self.get_option_market_data(symbol, expiry, strike, "C")
        fill = mkt.get("ask", 0)
        if fill <= 0:
            return {"status": "failed", "reason": "Unable to obtain ask price"}
        ib_symbol = self.normalize_symbol_for_ib(symbol)
        self._positions.append(
            {
                "symbol": ib_symbol,
                "strike": strike,
                "expiry": expiry,
                "quantity": quantity,
                "raw_avgCost": fill * 100,
                "multiplier": 100,
                "normalized_premium": fill,
                "audit_status": "OK",
            }
        )
        return {
            "status": "filled",
            "filled": quantity,
            "remaining": 0,
            "avgFillPrice": fill,
            "ib_status": "Filled",
            "timed_out": False,
            "order_id": self._order_id + 1,
        }

    def sell_option_limit(self, symbol: str, expiry: str, strike: float, quantity: int = 1) -> dict:
        if not self.connected:
            return {"status": "failed", "reason": "Not connected"}
        mkt = self.get_option_market_data(symbol, expiry, strike, "C")
        fill = mkt.get("bid", 0)
        if fill <= 0:
            return {"status": "failed", "reason": "Unable to obtain bid price"}
        ib_symbol = self.normalize_symbol_for_ib(symbol)
        self._positions = [
            p
            for p in self._positions
            if not (
                p["symbol"] == ib_symbol
                and p["expiry"] == expiry
                and p["strike"] == strike
            )
        ]
        return {
            "status": "filled",
            "filled": quantity,
            "remaining": 0,
            "avgFillPrice": fill,
            "ib_status": "Filled",
            "timed_out": False,
            "order_id": self._order_id + 1,
        }

    def get_positions(self) -> List[dict]:
        return list(self._positions)


def create_broker():
    if MOCK_IB:
        return MockIBBroker()
    return IBBroker()


def _in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


# ======================== Trading Engine ========================
class TradingEngine:
    def __init__(self, broker: IBBroker):
        self.broker = broker
        self.candidates: List[str] = []
        self.candidate_rows: List[dict] = []
        self.scan_timestamp: Optional[str] = None
        self.logs: List[str] = []
        self.order_audit_log: List[dict] = []

    def add_log(self, message: str) -> None:
        timestamp = datetime.datetime.now(EST).strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp} EST] {message}")
        logger.info(message)
        if len(self.logs) > 300:
            self.logs = self.logs[-300:]

    def add_order_log(self, record: dict) -> None:
        record["time"] = datetime.datetime.now(EST).strftime("%H:%M:%S")
        self.order_audit_log.append(record)
        if len(self.order_audit_log) > 50:
            self.order_audit_log = self.order_audit_log[-50:]

    def _get_est_time(self) -> datetime.datetime:
        return datetime.datetime.now(EST)

    def _get_est_time_str(self) -> str:
        return self._get_est_time().strftime("%H:%M")

    def _get_est_date(self) -> datetime.date:
        return self._get_est_time().date()

    def get_positions(self) -> List[dict]:
        return self.broker.get_positions()

    def load_sp500_symbols(self) -> pd.DataFrame:
        fallback = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "JPM", "V"],
                "name": [""] * 10,
                "sector": ["Technology"] * 10,
                "industry": [""] * 10,
            }
        )
        try:
            resp = requests.get(
                SP500_URL,
                timeout=30,
                headers={"User-Agent": "AetherNexus/3.4 (research bot; contact: local)"},
            )
            resp.raise_for_status()
            tables = pd.read_html(StringIO(resp.text))
            df = tables[0].copy()
            if "Symbol" not in df.columns:
                raise ValueError("S&P 500 table missing Symbol column")
            df = df.rename(
                columns={
                    "Symbol": "symbol",
                    "Security": "name",
                    "GICS Sector": "sector",
                    "GICS Sub-Industry": "industry",
                }
            )
            keep_cols = [c for c in ["symbol", "name", "sector", "industry"] if c in df.columns]
            df = df[keep_cols].dropna(subset=["symbol"])
            df["symbol"] = df["symbol"].astype(str).str.strip()
        except Exception as e:
            self.add_log(f"S&P 500 Wikipedia fetch failed ({e}) — using fallback symbol list")
            df = fallback
        if SCAN_MAX_SYMBOLS > 0:
            df = df.head(SCAN_MAX_SYMBOLS)
        return df

    def _select_candidate_contract(
        self, symbol: str, underlying_price: float, chain_df: pd.DataFrame
    ) -> Optional[Tuple[str, float]]:
        today = self._get_est_date()
        chain_df = chain_df.copy()
        chain_df["expiry_dt"] = pd.to_datetime(chain_df["expiry"])
        today_ts = pd.Timestamp(today)
        chain_df["days"] = (chain_df["expiry_dt"] - today_ts).dt.days
        valid = chain_df[(chain_df["days"] >= SCAN_MIN_DTE) & (chain_df["days"] <= SCAN_MAX_DTE)]
        if valid.empty:
            return None
        expiry = valid.sort_values("days")["expiry"].iloc[0]
        strikes = sorted(valid[valid["expiry"] == expiry]["strike"].tolist())
        if not strikes:
            return None
        target_strike = underlying_price * SCAN_TARGET_OTM
        strike = min(strikes, key=lambda x: abs(x - target_strike))
        return expiry, strike

    def _score_candidate(self, row: dict) -> float:
        volume_score = min(row["volume"] / 500, 1.0) * 30
        spread_score = max(0, 1 - row["spread_pct"] / MAX_SPREAD_PCT) * 25
        delta_score = max(0, 1 - abs(row["delta"] - 0.38) / 0.15) * 20
        theta_score = max(0, 1 - row["theta_ratio"] / MAX_THETA_RATIO) * 15
        premium_score = (
            max(0, 1 - abs(row["premium_dollars"] - (CAPITAL_PER_TRADE * 0.55)) / CAPITAL_PER_TRADE)
            * 10
        )
        return round(volume_score + spread_score + delta_score + theta_score + premium_score, 2)

    def pre_market_screen(self) -> List[str]:
        if not self.broker.connected:
            self.add_log("Connect to IB before running S&P 500 scan")
            return []

        self.add_log("Starting S&P 500 full universe scan...")
        self.candidates = []
        self.candidate_rows = []
        self.scan_timestamp = None

        universe_df = self.load_sp500_symbols()
        if universe_df.empty:
            self.add_log("S&P 500 universe empty — scan aborted")
            return []

        total = len(universe_df)
        self.add_log(f"Loaded S&P 500 universe: {total} symbols")

        progress_bar = None
        status_text = None
        if _in_streamlit():
            progress_bar = st.progress(0, text="Initializing scan...")
            status_text = st.empty()

        for i, (_, item) in enumerate(universe_df.iterrows()):
            symbol = item["symbol"]
            name = item.get("name", "")
            sector = item.get("sector", "")
            progress_pct = min((i + 1) / total, 1.0)
            if progress_bar is not None:
                progress_bar.progress(progress_pct, text=f"Scanning {symbol} ({i + 1}/{total})")
            elif (i + 1) % 10 == 0 or i + 1 == total:
                logger.info("Scan progress: %s (%d/%d)", symbol, i + 1, total)

            try:
                price = self.broker.get_underlying_price(symbol)
                time.sleep(SCAN_SLEEP_SEC)

                if not price or price < SCAN_MIN_PRICE or price > SCAN_MAX_PRICE:
                    continue

                chain_df = self.broker.get_option_chain(symbol)
                time.sleep(SCAN_SLEEP_SEC)
                if chain_df.empty:
                    continue

                contract_pick = self._select_candidate_contract(symbol, price, chain_df)
                if not contract_pick:
                    continue

                expiry, strike = contract_pick
                mkt = self.broker.get_option_market_data(symbol, expiry, strike, "C")
                time.sleep(SCAN_SLEEP_SEC)

                if not mkt or mkt.get("price", 0) <= 0:
                    continue

                bid, ask, option_price = mkt["bid"], mkt["ask"], mkt["price"]
                delta, gamma, theta, iv, volume = (
                    mkt["delta"],
                    mkt["gamma"],
                    mkt["theta"],
                    mkt["iv"],
                    mkt["volume"],
                )

                if bid <= 0 or ask <= 0:
                    continue

                spread_pct = (ask - bid) / ((ask + bid) / 2)
                theta_ratio = abs(theta) / option_price if option_price > 0 else 999
                premium_dollars = option_price * 100

                if spread_pct > MAX_SPREAD_PCT or iv > MAX_IV_ABS:
                    continue
                if not (MIN_DELTA <= delta <= MAX_DELTA) or gamma < MIN_GAMMA:
                    continue
                if (
                    theta_ratio > MAX_THETA_RATIO
                    or volume < MIN_OPT_VOLUME
                    or premium_dollars > CAPITAL_PER_TRADE
                ):
                    continue

                row = {
                    "symbol": symbol,
                    "name": name,
                    "sector": sector,
                    "underlying_price": round(price, 2),
                    "expiry": expiry,
                    "strike": strike,
                    "option_price": round(option_price, 2),
                    "bid": round(bid, 2),
                    "ask": round(ask, 2),
                    "spread_pct": round(spread_pct, 4),
                    "delta": round(delta, 4),
                    "gamma": round(gamma, 4),
                    "theta": round(theta, 4),
                    "theta_ratio": round(theta_ratio, 4),
                    "iv": round(iv, 4),
                    "volume": int(volume),
                    "premium_dollars": round(premium_dollars, 2),
                }
                row["score"] = self._score_candidate(row)
                self.candidate_rows.append(row)
                if status_text is not None:
                    status_text.text(f"Candidates found: {len(self.candidate_rows)}")

            except Exception as e:
                self.add_log(f"{symbol} scan error: {e}")
                continue

        if progress_bar is not None:
            progress_bar.empty()
        if status_text is not None:
            status_text.empty()

        if not self.candidate_rows:
            self.add_log("No candidates passed filters this scan")
            send_notification("Aether Nexus: S&P 500 scan returned no candidates")
            return []

        df = pd.DataFrame(self.candidate_rows)
        df = df.sort_values("score", ascending=False).head(TOP_CANDIDATES)
        self.candidate_rows = df.to_dict("records")
        self.candidates = df["symbol"].tolist()
        self.scan_timestamp = datetime.datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S EST")

        msg = "S&P 500 scan complete. Top candidates: " + ", ".join(self.candidates)
        self.add_log(msg)
        send_notification(msg)
        return self.candidates

    def _get_candidate_contract_from_screen(self, symbol: str) -> Optional[dict]:
        target = self.broker.normalize_symbol_for_ib(symbol)
        for row in self.candidate_rows:
            if self.broker.normalize_symbol_for_ib(row["symbol"]) == target:
                return row
        return None

    def check_and_buy(self) -> None:
        real_positions = self.get_positions()
        if len(real_positions) >= MAX_POSITIONS:
            self.add_log(f"Position limit reached ({len(real_positions)}/{MAX_POSITIONS})")
            return

        current_time = self._get_est_time_str()
        if not (TRADING_START <= current_time <= TRADING_END):
            self.add_log(f"Outside trading window: {current_time} EST")
            return

        if not self.candidates:
            self.add_log("Candidate pool empty — run S&P 500 scan first")
            return

        for sym in self.candidates:
            if any(
                self.broker.normalize_symbol_for_ib(p["symbol"])
                == self.broker.normalize_symbol_for_ib(sym)
                for p in real_positions
            ):
                self.add_log(f"{sym} already held — skipping")
                continue

            selected = self._get_candidate_contract_from_screen(sym)
            if not selected:
                self.add_log(f"{sym} missing screened contract data — skipping")
                continue

            expiry, strike = selected["expiry"], selected["strike"]
            self.add_log(
                f"Buy attempt: {sym} Call {strike} exp {expiry} / score {selected.get('score')}"
            )

            order_result = self.broker.buy_call_option_limit(sym, expiry, strike, quantity=1)
            audit = {
                "action": "BUY",
                "symbol": sym,
                "strike": strike,
                "expiry": expiry,
                "status": order_result.get("status"),
                "filled": order_result.get("filled", 0),
                "remaining": order_result.get("remaining", 0),
                "avgFillPrice": order_result.get("avgFillPrice", 0),
                "ib_status": order_result.get("ib_status", ""),
                "timed_out": order_result.get("timed_out", False),
                "order_id": order_result.get("order_id"),
                "reason": order_result.get("reason", ""),
                "attempt": 1,
            }
            self.add_order_log(audit)

            status = order_result.get("status")
            if status in ("filled", "partial_fill"):
                filled_qty = order_result.get("filled", 0)
                msg = (
                    f"BUY {sym} Call {strike} exp {expiry}\n"
                    f"Filled {filled_qty} @ ${order_result.get('avgFillPrice', 0):.2f}\n"
                    f"IB status: {order_result.get('ib_status', '')}"
                )
                if status == "partial_fill":
                    msg += f"\nPartial fill: {order_result.get('remaining', 0)} remaining"
                self.add_log(msg)
                send_notification(msg, priority="critical")
            elif status == "timeout_cancelled":
                self.add_log(
                    f"{sym} order timeout — IB status {order_result.get('ib_status', 'UNKNOWN')}"
                )
            else:
                self.add_log(f"Buy failed: {order_result.get('reason', 'unknown')}")

            # Intentional single-entry-per-cycle: break after first buy attempt
            break

    def monitor_positions(self) -> None:
        current_time = self._get_est_time_str()
        for pos in self.get_positions():
            sym, strike, expiry = pos["symbol"], pos["strike"], pos["expiry"]
            entry_price = pos.get("normalized_premium")
            if entry_price is None or entry_price <= 0:
                self.add_log(
                    f"Skipping {sym} auto-risk: normalized_premium missing — manual review required"
                )
                continue

            mkt = self.broker.get_option_market_data(sym, expiry, strike, "C")
            if not mkt or mkt.get("price", 0) <= 0:
                self.add_log(f"{sym} position check: no valid market data")
                continue

            current_price = mkt["price"]
            pnl_pct = (current_price - entry_price) / entry_price
            action = None
            if pnl_pct <= -STOP_LOSS_PCT:
                action = "STOP_LOSS"
            elif pnl_pct >= TAKE_PROFIT_PCT:
                action = "TAKE_PROFIT"
            elif current_time >= FORCE_CLOSE_TIME:
                action = "FORCE_CLOSE"

            if action:
                self._close_position(pos, current_price, pnl_pct, action)

    def _close_position(self, pos: dict, current_price: float, pnl_pct: float, reason: str) -> None:
        last_result = None
        for attempt in range(1, CLOSE_MAX_RETRIES + 1):
            order_result = self.broker.sell_option_limit(
                pos["symbol"], pos["expiry"], pos["strike"], pos["quantity"]
            )
            last_result = order_result
            audit = {
                "action": "SELL",
                "symbol": pos["symbol"],
                "strike": pos["strike"],
                "expiry": pos["expiry"],
                "status": order_result.get("status"),
                "filled": order_result.get("filled", 0),
                "remaining": order_result.get("remaining", 0),
                "avgFillPrice": order_result.get("avgFillPrice", 0),
                "ib_status": order_result.get("ib_status", ""),
                "timed_out": order_result.get("timed_out", False),
                "order_id": order_result.get("order_id"),
                "reason": reason if reason else order_result.get("reason", ""),
                "attempt": attempt,
            }
            self.add_order_log(audit)

            status = order_result.get("status")
            if status in ("filled", "partial_fill"):
                break
            if status == "timeout_cancelled" and attempt < CLOSE_MAX_RETRIES:
                self.add_log(
                    f"{pos['symbol']} close attempt {attempt} timed out — "
                    f"retrying in {CLOSE_RETRY_DELAY}s..."
                )
                time.sleep(CLOSE_RETRY_DELAY)
                continue
            break

        status = last_result.get("status") if last_result else "failed"
        if status in ("filled", "partial_fill"):
            filled_qty = last_result.get("filled", pos["quantity"])
            multiplier = pos.get("multiplier")
            entry_price = pos.get("normalized_premium")
            exit_price = last_result.get("avgFillPrice", 0)
            if multiplier and entry_price is not None:
                profit = (exit_price - entry_price) * filled_qty * multiplier
                profit_text = f"${profit:.2f}"
            else:
                profit_text = "UNKNOWN_MULTIPLIER"

            msg = (
                f"{reason} {pos['symbol']} Call\n"
                f"Entry: ${entry_price:.2f} Exit: ${exit_price:.2f}\n"
                f"P&L: {pnl_pct:.1%} ({profit_text})\n"
                f"IB status: {last_result.get('ib_status', '')}"
            )
            if status == "partial_fill":
                msg += f"\nPartial close: {filled_qty}/{pos['quantity']} contracts"
            self.add_log(msg)
            send_notification(msg, priority="critical")
        elif status == "timeout_cancelled":
            fail_msg = (
                f"CLOSE FAILED {pos['symbol']} Call {pos['strike']}\n"
                f"All {CLOSE_MAX_RETRIES} attempts timed out — manual intervention required"
            )
            self.add_log(fail_msg)
            send_notification(fail_msg, priority="critical")
        else:
            fail_msg = f"Close failed: {last_result.get('reason', 'unknown') if last_result else 'unknown'}"
            self.add_log(fail_msg)
            send_notification(fail_msg, priority="critical")

    def emergency_close_all(self) -> None:
        for pos in self.get_positions():
            self._close_position(pos, 0, 0, "EMERGENCY_CLOSE")
        self.add_log("Emergency close-all workflow executed")


def render_dashboard() -> None:
    st.set_page_config(page_title="Aether Nexus", layout="wide", page_icon="🌌")

    st.markdown(
        """
<style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    [data-testid="stSidebar"] { background-color: #161b22; }
    [data-testid="stMetricValue"] { color: #58a6ff; }
    [data-testid="stMetricLabel"] { color: #8b949e; }
    h1, h2, h3, h4 { color: #e6edf3 !important; }
    .stCaption { color: #8b949e !important; }
    div[data-testid="stDataFrame"] { border: 1px solid #30363d; border-radius: 6px; }
    .stButton > button[kind="primary"] {
        background-color: #238636; border-color: #238636;
    }
    .stButton > button[kind="secondary"] {
        background-color: #da3633; color: #ffffff; border-color: #da3633;
    }
</style>
""",
        unsafe_allow_html=True,
    )

    st.title("🌌 Aether Nexus Command Center")
    st.caption("Synapse AI Orchestration Layer — R3.4 Opus Audit Consolidated")

    if "broker" not in st.session_state:
        st.session_state.broker = create_broker()
    if "engine" not in st.session_state:
        st.session_state.engine = TradingEngine(st.session_state.broker)
    if "ib_connected" not in st.session_state:
        st.session_state.ib_connected = False

    broker = st.session_state.broker
    engine = st.session_state.engine

    with st.sidebar:
        st.header("System Control")
        if MOCK_IB:
            st.warning("Mock IB mode (MOCK_IB=true)")
        elif LIVE_TRADING_ENABLED:
            st.warning("LIVE trading mode enabled")
        else:
            st.info("Paper trading mode (default)")

        if not st.session_state.ib_connected:
            if st.button("Connect IB", type="primary", use_container_width=True):
                if broker.connect():
                    st.session_state.ib_connected = True
                    engine.add_log("IB connected")
                    st.rerun()
                else:
                    st.error("Connection failed — check TWS/Gateway and port settings")
        else:
            st.success("IB connected")
            if st.button("Disconnect IB", use_container_width=True):
                broker.disconnect()
                st.session_state.ib_connected = False
                engine.add_log("IB disconnected")
                st.rerun()

        st.divider()
        st.subheader("Manual Actions")
        if st.button("S&P 500 Full Scan", use_container_width=True):
            engine.pre_market_screen()
            st.rerun()
        if st.button("Check Buy Signals", use_container_width=True):
            engine.check_and_buy()
            st.rerun()
        if st.button("Monitor Positions", use_container_width=True):
            engine.monitor_positions()
            st.rerun()
        if st.button("Emergency Close All", use_container_width=True, type="secondary"):
            engine.emergency_close_all()
            st.rerun()

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Live Positions / Audit View")
        positions = engine.get_positions()
        if positions:
            df_pos = pd.DataFrame(positions)
            col_order = [
                "symbol",
                "strike",
                "expiry",
                "quantity",
                "raw_avgCost",
                "multiplier",
                "normalized_premium",
                "audit_status",
            ]
            df_pos = df_pos[[c for c in col_order if c in df_pos.columns]]
            st.dataframe(df_pos, use_container_width=True)
        else:
            st.info("No open positions")

        st.subheader("S&P 500 Scan Candidates")
        if engine.candidate_rows:
            if engine.scan_timestamp:
                st.caption(f"Scan timestamp: {engine.scan_timestamp}")
            df_candidates = pd.DataFrame(engine.candidate_rows)
            show_cols = [
                "symbol",
                "score",
                "sector",
                "underlying_price",
                "expiry",
                "strike",
                "option_price",
                "bid",
                "ask",
                "spread_pct",
                "delta",
                "gamma",
                "theta_ratio",
                "iv",
                "volume",
                "premium_dollars",
            ]
            show_cols = [c for c in show_cols if c in df_candidates.columns]
            st.dataframe(df_candidates[show_cols], use_container_width=True)
        else:
            st.info("No scan results — run S&P 500 Full Scan from the sidebar")

    with col2:
        st.subheader("System Status")
        mode = "MOCK" if MOCK_IB else ("LIVE" if LIVE_TRADING_ENABLED else "PAPER")
        st.metric("Trading Mode", mode)
        st.metric("IB Connection", "Connected" if st.session_state.ib_connected else "Disconnected")
        st.metric("Position Count", len(positions))
        st.metric("Candidate Count", len(engine.candidates))
        st.metric("EST Time", datetime.datetime.now(EST).strftime("%H:%M:%S"))
        st.caption("Set SCAN_MAX_SYMBOLS=30 in .env for quick tests; use 0 for full scan.")

    st.divider()
    st.subheader("Order Audit Log (last 50)")
    if engine.order_audit_log:
        audit_cols = [
            "time",
            "action",
            "symbol",
            "strike",
            "status",
            "filled",
            "remaining",
            "avgFillPrice",
            "ib_status",
            "timed_out",
            "attempt",
        ]
        df_audit = pd.DataFrame(engine.order_audit_log)
        df_audit = df_audit[[c for c in audit_cols if c in df_audit.columns]]
        st.dataframe(df_audit, use_container_width=True)
    else:
        st.info("No order records yet")

    st.divider()
    st.subheader("Agent Log (last 35 lines)")
    st.code("\n".join(engine.logs[-35:]), language="log")

    if st.button("Manual Refresh"):
        st.rerun()


if _in_streamlit():
    render_dashboard()
