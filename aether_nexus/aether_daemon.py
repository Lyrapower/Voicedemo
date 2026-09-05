#!/usr/bin/env python3
"""
Aether Nexus R5.4.1 — Daemon
Exclusive IB connection, scheduled scan + auto trading. Pairs with Pool/BFS Dry Run.
"""
import asyncio
import datetime
import logging
import math
import os
import signal
import sys
import time
from io import StringIO
from typing import List, Optional, Tuple

import nest_asyncio
import pandas as pd
import requests
from ib_insync import IB, LimitOrder, Option, Stock

nest_asyncio.apply()
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aether_shared import (  # noqa: E402
    AETHER_VERSION,
    BUY_CHECK_INTERVAL_SEC,
    CAPITAL_PER_TRADE,
    CLOSE_MAX_RETRIES,
    CLOSE_RETRY_DELAY,
    EST,
    FORCE_CLOSE_TIME,
    IB_CLIENT_ID,
    IB_HOST,
    IB_PORT,
    LIVE_PORT,
    LIVE_TRADING_ENABLED,
    CAPITAL_DAEMON_COMMANDS,
    capital_execution_allowed,
    MAX_DELTA,
    MAX_IV_ABS,
    MAX_POSITIONS,
    MAX_SPREAD_PCT,
    MAX_THETA_RATIO,
    MIN_DELTA,
    MIN_GAMMA,
    MIN_OPT_VOLUME,
    MONITOR_INTERVAL_SEC,
    ORDER_TIMEOUT,
    PAPER_PORT,
    SCAN_MAX_DTE,
    SCAN_MAX_PRICE,
    SCAN_MAX_SYMBOLS,
    SCAN_MIN_DTE,
    SCAN_MIN_PRICE,
    SCAN_POST_MARKET,
    SCAN_PRE_MARKET,
    SCAN_REMINDER_MIN,
    SCAN_SLEEP_SEC,
    SCAN_TARGET_OTM,
    SP500_URL,
    STATE_DIR,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    TOP_CANDIDATES,
    TRADING_END,
    TRADING_START,
    atomic_write_json,
    dryrun_row_to_ib_candidate,
    IB_SCAN_SOURCE,
    load_latest_dryrun_scan,
    logger,
    poll_commands,
    send_notification,
)

# ======================== IB Broker ========================
class IBBroker:
    def __init__(self):
        self.ib = IB()
        self.connected = False
        self.is_live = False

    def connect(self) -> bool:
        actual_port = IB_PORT
        if LIVE_TRADING_ENABLED and actual_port != LIVE_PORT:
            logger.error("LIVE_TRADING_ENABLED=true but port is %s, expected %s", actual_port, LIVE_PORT)
            return False
        if not LIVE_TRADING_ENABLED and actual_port == LIVE_PORT:
            logger.error("LIVE_TRADING_ENABLED=false but port is %s, expected %s", LIVE_PORT, PAPER_PORT)
            return False
        self.is_live = LIVE_TRADING_ENABLED
        try:
            if self.ib.isConnected():
                self.ib.disconnect()
            self.ib.connect(IB_HOST, actual_port, clientId=IB_CLIENT_ID, timeout=20)
            self.ib.reqMarketDataType(1 if self.is_live else 3)
            self.connected = True
            mode = "LIVE" if self.is_live else "PAPER"
            logger.info("IB connected: port %s / %s (delayed data on paper)", actual_port, mode)
            return True
        except Exception as e:
            logger.error("IB connection failed: %s", e or "timeout — Gateway may not be logged in")
            self.connected = False
            try:
                self.ib.disconnect()
            except Exception:
                pass
            self.ib = IB()
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
            m = int(float(raw_multiplier))
            return m if m > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def normalize_symbol_for_ib(symbol: str) -> str:
        return symbol.replace(".", " ").strip()

    def get_underlying_price(self, symbol: str) -> Optional[float]:
        if not self.connected:
            return None
        try:
            ib_sym = self.normalize_symbol_for_ib(symbol)
            stock = Stock(ib_sym, "SMART", "USD")
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
            logger.error("Underlying price failed %s: %s", symbol, e)
            return None

    def get_option_chain(self, symbol: str) -> pd.DataFrame:
        if not self.connected:
            return pd.DataFrame()
        try:
            ib_sym = self.normalize_symbol_for_ib(symbol)
            stock = Stock(ib_sym, "SMART", "USD")
            details = self.ib.reqContractDetails(stock)
            if not details:
                return pd.DataFrame()
            con_id = details[0].contract.conId
            chains = self.ib.reqSecDefOptParams(ib_sym, "", "STK", con_id)
            rows = []
            for chain in chains:
                for strike in chain.strikes:
                    for expiry in chain.expirations:
                        rows.append({"expiry": expiry, "strike": strike})
            return pd.DataFrame(rows)
        except Exception as e:
            logger.error("Option chain failed %s: %s", symbol, e)
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

    def get_option_market_data(self, symbol: str, expiry: str, strike: float, right: str = "C") -> dict:
        if not self.connected:
            return {}
        try:
            ib_sym = self.normalize_symbol_for_ib(symbol)
            contract = Option(ib_sym, expiry, strike, right, "SMART", currency="USD")
            self.ib.qualifyContracts(contract)
            ticker = self.ib.reqMktData(contract, "221", False, False)
            self.ib.sleep(2)
            price = ticker.marketPrice()
            bid = ticker.bid if ticker.bid is not None and ticker.bid != -1 else 0
            ask = ticker.ask if ticker.ask is not None and ticker.ask != -1 else 0
            if (not price or price <= 0) and bid > 0 and ask > 0:
                price = (bid + ask) / 2
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
            logger.error("Option market data failed %s %s %s: %s", symbol, expiry, strike, e)
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
                "reason": "Order timed out; cancel requested, no fill",
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
            ib_sym = self.normalize_symbol_for_ib(symbol)
            contract = Option(ib_sym, expiry, strike, "C", "SMART", currency="USD")
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
            ib_sym = self.normalize_symbol_for_ib(symbol)
            contract = Option(ib_sym, expiry, strike, "C", "SMART", currency="USD")
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


# ======================== Trading Engine ========================
class TradingEngine:
    def __init__(self, broker: IBBroker):
        self.broker = broker
        self.candidates: List[str] = []
        self.candidate_rows: List[dict] = []
        self.scan_timestamp: Optional[str] = None
        self.candidate_source: str = IB_SCAN_SOURCE
        self._last_dryrun_scan_time: Optional[str] = None
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
                headers={"User-Agent": "AetherNexus/5.3 (research bot; contact: local)"},
            )
            resp.raise_for_status()
            df = pd.read_html(StringIO(resp.text))[0].copy()
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
            self.add_log(f"S&P 500 Wikipedia fetch failed ({e}) — using fallback list")
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
            max(0, 1 - abs(row["premium_dollars"] - (CAPITAL_PER_TRADE * 0.55)) / CAPITAL_PER_TRADE) * 10
        )
        return round(volume_score + spread_score + delta_score + theta_score + premium_score, 2)

    def load_candidates_from_dryrun(self, notify: bool = False) -> List[str]:
        """Load latest Dry Run BFS scan from aether_dryrun → IB buy list."""
        payload = load_latest_dryrun_scan()
        scan_time = payload.get("scan_time")
        if scan_time and scan_time == self._last_dryrun_scan_time:
            return self.candidates

        cands = payload.get("candidates") or []
        scan_mode = payload.get("scan_mode", "sp500")
        self.candidate_rows = [dryrun_row_to_ib_candidate(c) for c in cands]
        for row in self.candidate_rows:
            row["scan_mode"] = scan_mode
        self.candidates = [r["symbol"] for r in self.candidate_rows if r.get("symbol")]
        self.scan_timestamp = (scan_time or "")[:19]
        self.candidate_source = f"dryrun_{scan_mode}"
        self._last_dryrun_scan_time = scan_time

        if self.candidate_rows:
            msg = (
                f"Dry Run {scan_mode.upper()} → IB: "
                + ", ".join(self.candidates)
            )
            self.add_log(msg)
            if notify:
                send_notification(msg)
        else:
            self.add_log("Dry Run scan empty — no IB buy candidates loaded")
        return self.candidates

    def refresh_candidates(self, notify: bool = False) -> List[str]:
        if IB_SCAN_SOURCE == "dryrun":
            return self.load_candidates_from_dryrun(notify=notify)
        return self.pre_market_screen()

    def pre_market_screen(self) -> List[str]:
        if IB_SCAN_SOURCE == "dryrun":
            return self.load_candidates_from_dryrun(notify=True)
        if not self.broker.connected:
            self.add_log("Connect to IB before running S&P 500 scan")
            return []

        self.add_log("Starting IB native S&P 500 scan...")
        self.candidates = []
        self.candidate_rows = []
        self.scan_timestamp = None
        self.candidate_source = "ib_native"

        universe_df = self.load_sp500_symbols()
        if universe_df.empty:
            self.add_log("S&P 500 universe empty — scan aborted")
            return []

        total = len(universe_df)
        self.add_log(f"Loaded S&P 500 universe: {total} symbols")

        for i, (_, item) in enumerate(universe_df.iterrows()):
            symbol = item["symbol"]
            name = item.get("name", "")
            sector = item.get("sector", "")
            if (i + 1) % 25 == 0 or i + 1 == total:
                self.add_log(f"Scan progress: {symbol} ({i + 1}/{total})")

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
                if theta_ratio > MAX_THETA_RATIO or volume < MIN_OPT_VOLUME or premium_dollars > CAPITAL_PER_TRADE:
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
            except Exception as e:
                self.add_log(f"{symbol} scan error: {e}")
                continue

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
        ok, reason = capital_execution_allowed(broker_connected=self.broker.connected)
        if not ok:
            self.add_log(f"R4 v2 DENY check_and_buy: {reason}")
            logger.warning("R4 v2 DENY check_and_buy: %s", reason)
            return
        real_positions = self.get_positions()
        if len(real_positions) >= MAX_POSITIONS:
            return

        current_time = self._get_est_time_str()
        if not (TRADING_START <= current_time <= TRADING_END):
            return

        if not self.candidates:
            return

        for sym in self.candidates:
            if any(
                self.broker.normalize_symbol_for_ib(p["symbol"])
                == self.broker.normalize_symbol_for_ib(sym)
                for p in real_positions
            ):
                continue

            selected = self._get_candidate_contract_from_screen(sym)
            if not selected:
                continue

            expiry, strike = selected["expiry"], selected["strike"]
            self.add_log(f"Buy attempt: {sym} Call {strike} exp {expiry} / score {selected.get('score')}")

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
                self.add_log(f"{sym} order timeout cancelled")
            else:
                self.add_log(f"Buy failed: {order_result.get('reason', 'unknown')}")

            # Intentional single-entry-per-cycle
            break

    def monitor_positions(self) -> None:
        current_time = self._get_est_time_str()
        for pos in self.get_positions():
            sym, strike, expiry = pos["symbol"], pos["strike"], pos["expiry"]
            entry_price = pos.get("normalized_premium")
            if entry_price is None or entry_price <= 0:
                self.add_log(f"Skip {sym} auto-risk: normalized_premium missing")
                continue

            mkt = self.broker.get_option_market_data(sym, expiry, strike, "C")
            if not mkt or mkt.get("price", 0) <= 0:
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
                "reason": reason,
                "attempt": attempt,
            }
            self.add_order_log(audit)

            status = order_result.get("status")
            if status in ("filled", "partial_fill"):
                break
            if status == "timeout_cancelled" and attempt < CLOSE_MAX_RETRIES:
                self.add_log(f"{pos['symbol']} close attempt {attempt} timed out — retry in {CLOSE_RETRY_DELAY}s")
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
                f"P&L: {pnl_pct:.1%} ({profit_text})"
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
        ok, reason = capital_execution_allowed(broker_connected=self.broker.connected)
        if not ok:
            self.add_log(f"R4 v2 DENY emergency_close: {reason}")
            logger.warning("R4 v2 DENY emergency_close: %s", reason)
            return
        for pos in self.get_positions():
            self._close_position(pos, 0, 0, "EMERGENCY_CLOSE")
        self.add_log("Emergency close-all executed")


# ======================== Daemon main loop ========================
class AetherDaemon:
    def __init__(self):
        self.broker = IBBroker()
        self.engine = TradingEngine(self.broker)
        self.running = True
        self._last_scan_times: set = set()
        self._last_reminder_times: set = set()
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info("Shutdown signal received")
        self.running = False
        self.broker.disconnect()
        self._write_status(connected=False)
        sys.exit(0)

    def _write_status(self, connected: bool = None) -> None:
        status = {
            "connected": connected if connected is not None else self.broker.connected,
            "is_live": self.broker.is_live,
            "live_trading_enabled": LIVE_TRADING_ENABLED,
            "heartbeat": datetime.datetime.now(EST).isoformat(),
            "pid": os.getpid(),
        }
        atomic_write_json(os.path.join(STATE_DIR, "status.json"), status)

    def _write_state(self) -> None:
        atomic_write_json(os.path.join(STATE_DIR, "positions.json"), self.engine.get_positions())
        atomic_write_json(
            os.path.join(STATE_DIR, "candidates.json"),
            {
                "rows": self.engine.candidate_rows,
                "symbols": self.engine.candidates,
                "scan_timestamp": self.engine.scan_timestamp,
                "source": self.engine.candidate_source,
            },
        )
        atomic_write_json(os.path.join(STATE_DIR, "logs.json"), self.engine.logs[-300:])
        atomic_write_json(os.path.join(STATE_DIR, "audit.json"), self.engine.order_audit_log[-50:])
        self._write_status()

    def _check_scan_reminders(self) -> None:
        if IB_SCAN_SOURCE == "dryrun":
            return
        now = datetime.datetime.now(EST)
        current_time = now.strftime("%H:%M")
        today_key = now.strftime("%Y-%m-%d")

        for scan_time in [SCAN_PRE_MARKET, SCAN_POST_MARKET]:
            try:
                scan_dt = datetime.datetime.strptime(scan_time, "%H:%M")
                reminder_dt = scan_dt - datetime.timedelta(minutes=SCAN_REMINDER_MIN)
                reminder_time = reminder_dt.strftime("%H:%M")
            except ValueError:
                continue

            reminder_key = f"{today_key}_reminder_{scan_time}"
            if current_time == reminder_time and reminder_key not in self._last_reminder_times:
                self._last_reminder_times.add(reminder_key)
                send_notification(
                    f"Aether Nexus reminder: S&P 500 scan in {SCAN_REMINDER_MIN} min "
                    f"({scan_time} EST)"
                )

        self._last_reminder_times = {k for k in self._last_reminder_times if k.startswith(today_key)}

    def _check_scheduled_scans(self) -> None:
        if IB_SCAN_SOURCE == "dryrun":
            return
        now = datetime.datetime.now(EST)
        current_time = now.strftime("%H:%M")
        today_key = now.strftime("%Y-%m-%d")
        for scan_time in [SCAN_PRE_MARKET, SCAN_POST_MARKET]:
            scan_key = f"{today_key}_{scan_time}"
            if current_time == scan_time and scan_key not in self._last_scan_times:
                self._last_scan_times.add(scan_key)
                self.engine.add_log(f"Scheduled scan triggered: {scan_time} EST")
                self.engine.pre_market_screen()
        self._last_scan_times = {k for k in self._last_scan_times if k.startswith(today_key)}

    def _handle_commands(self) -> None:
        for cmd in poll_commands():
            cmd_name = str(cmd.get("cmd") or "")
            # Forged metadata in the .cmd JSON is not authority.
            _ignored = {k: cmd.get(k) for k in ("authorized", "role", "source", "benchmark") if k in cmd}
            if _ignored:
                logger.info("R4 v2 ignore client metadata on cmd=%s keys=%s", cmd_name, sorted(_ignored))
            self.engine.add_log(f"Manual command received: {cmd_name}")
            if cmd_name in CAPITAL_DAEMON_COMMANDS:
                ok, reason = capital_execution_allowed(broker_connected=self.broker.connected)
                if not ok:
                    logger.warning("R4 v2 DENY capital cmd=%s reason=%s", cmd_name, reason)
                    self.engine.add_log(f"R4 v2 DENY {cmd_name}: {reason}")
                    continue
            if cmd_name == "scan":
                self.engine.refresh_candidates(notify=True)
            elif cmd_name == "buy":
                self.engine.check_and_buy()
            elif cmd_name == "monitor":
                self.engine.monitor_positions()
            elif cmd_name == "emergency_close":
                self.engine.emergency_close_all()

    def _ib_trading_required(self) -> bool:
        """Dryrun scan-only + live trading off → skip IB connect loop (Alpaca scans on nexus-dryrun)."""
        return LIVE_TRADING_ENABLED or IB_SCAN_SOURCE != "dryrun"

    def run(self) -> None:
        logger.info(
            "Aether Nexus Daemon starting (IB_SCAN_SOURCE=%s live=%s ib_required=%s)",
            IB_SCAN_SOURCE,
            LIVE_TRADING_ENABLED,
            self._ib_trading_required(),
        )
        notified_connected = False
        ib_skip_logged = False

        while self.running:
            try:
                if not self._ib_trading_required():
                    if not ib_skip_logged:
                        logger.info(
                            "IB connect skipped — dryrun scan path uses Alpaca via nexus-dryrun "
                            "(set LIVE_TRADING_ENABLED=true to enable IB trading leg)"
                        )
                        ib_skip_logged = True
                    self._write_status(connected=False)
                    self._handle_commands()
                    self.engine.load_candidates_from_dryrun()
                    self._write_state()
                    time.sleep(10)
                    continue

                if not self.broker.connected:
                    self._write_status(connected=False)
                    if self.broker.connect():
                        self.engine.add_log("Daemon started — IB connected")
                        if not notified_connected:
                            send_notification(
                                f"Aether Nexus {AETHER_VERSION} Daemon started — IB connected"
                            )
                            notified_connected = True
                    else:
                        logger.warning(
                            "IB not ready — retry in 30s (open IB Gateway/TWS, ensure logged in)"
                        )
                        for _ in range(3):
                            self._write_status(connected=False)
                            time.sleep(10)
                        continue

                now = time.time()
                if not hasattr(self, "_last_monitor"):
                    self._last_monitor = 0.0
                    self._last_buy_check = 0.0

                self._handle_commands()
                if IB_SCAN_SOURCE == "dryrun":
                    self.engine.load_candidates_from_dryrun()
                else:
                    self._check_scan_reminders()
                    self._check_scheduled_scans()

                if now - self._last_monitor >= MONITOR_INTERVAL_SEC:
                    self.engine.monitor_positions()
                    self._last_monitor = now

                if now - self._last_buy_check >= BUY_CHECK_INTERVAL_SEC:
                    self.engine.check_and_buy()
                    self._last_buy_check = now

                self._write_state()
                time.sleep(10)
            except Exception as e:
                logger.error("Main loop error: %s", e)
                self.engine.add_log(f"Main loop error: {e}")
                self.broker.connected = False
                time.sleep(30)


if __name__ == "__main__":
    from aether_shared import attach_nexus_live_log, logger as nexus_logger  # noqa: E402

    attach_nexus_live_log(nexus_logger)
    AetherDaemon().run()
