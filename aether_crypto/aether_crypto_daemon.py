#!/usr/bin/env python3
"""
Aether Nexus Crypto V1.2 — Daemon (现货合规版)
7×24 加密货币现货自动交易引擎

V1.2 vs V1.1 逐条（对应工单九条）:
1. 杠杆语义全拆：无 defaultType=swap / set_leverage / :USDT 永续 / fetch_positions；
   宇宙 = -USD 现货对（默认 BTC/ETH/SOL，env SPOT_UNIVERSE 可扩）
2. 持仓=余额：仓位状态从 fetch_balance + 本地 positions.json 对账；
   卖出量 = min(本地记录, 交易所可用余额)——超卖防护（现货无 reduceOnly）
3. 止损/止盈：交易所侧优先（ccxt stop 单 + stopPrice）+ 本地 monitor 兜底对账
4. 参数语义改：无杠杆，SL/TP 即价格百分比；MAX_LEVERAGE 键删除；默认 SL 0.05 / TP 0.15
5. 合规断言：BLOCKED_EXCHANGES={"bybit","binance"}，EXCHANGE_ID 命中启动即死
6. live 双闸：LIVE_TRADING=false 默认 + LIVE_ACK=YES_I_AUTHORIZED_LIVE；启动 banner 打印档位
7. 信号层不动：开仓信号仍订单簿不平衡（已知限制，策略轮再改）
8. 通知信道：Pushover/Telegram 保留，默认空 key 即静默
9. registry 登记：capability aether.crypto.spot_v12，daemon 无监听端口

三档模式（TRADING_MODE）:
- paper   — 不连交易所私有端，本地构造订单全字段日志（验收 B/D 默认档）
- sandbox — coinbaseexchange + set_sandbox_mode(True)，真实沙盒 API
- live    — 须 LIVE_TRADING=true 且 LIVE_ACK=YES_I_AUTHORIZED_LIVE 双键
"""

import time
import datetime
import signal
import ccxt
from typing import List, Optional, Dict

from aether_crypto_shared import *


# ======================== 交易所接口（V1.2 现货） ========================
class CryptoExchange:
    def __init__(self, mode: str):
        self.mode = mode  # PAPER / SANDBOX / LIVE
        self.paper = (mode == "PAPER")
        if self.paper:
            self.exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
            self.exchange.load_markets()
            logger.info(f"[PAPER] 交易所 {EXCHANGE_ID} public 连接成功 markets={len(self.exchange.markets)}")
            return
        params = {
            "apiKey": EXCHANGE_API_KEY,
            "secret": EXCHANGE_SECRET_KEY,
            "enableRateLimit": True,
        }
        if EXCHANGE_PASSPHRASE:
            params["password"] = EXCHANGE_PASSPHRASE
        self.exchange = getattr(ccxt, EXCHANGE_ID)(params)
        if mode == "SANDBOX":
            self.exchange.set_sandbox_mode(True)
        self.exchange.load_markets()
        logger.info(f"[{mode}] 交易所 {EXCHANGE_ID} 连接成功 markets={len(self.exchange.markets)}")
        if mode == "LIVE":
            send_notification(f"⚠️ Aether Crypto V1.2 以 LIVE 模式连接 {EXCHANGE_ID}", priority="critical")

    @property
    def markets(self):
        return self.exchange.markets

    def get_top_symbols(self, limit: int = 30) -> List[str]:
        """V1.2 #1: -USD 现货对，按 24h 成交额排序。只保留 spot，剔除 swap。"""
        try:
            tickers = self.exchange.fetch_tickers()
            spots = []
            for sym, t in tickers.items():
                m = self.markets.get(sym)
                if not m or not m.get("spot"):
                    continue
                if m.get("quote") != "USD":
                    continue
                if SPOT_UNIVERSE and sym not in SPOT_UNIVERSE:
                    continue
                qv = t.get("quoteVolume") or 0
                if qv < MIN_QUOTE_VOLUME_USD:
                    continue
                spots.append((sym, qv))
            spots.sort(key=lambda x: -x[1])
            return [s for s, _ in spots[:limit]]
        except Exception as e:
            logger.error(f"获取交易对失败: {e}")
            fb = SPOT_UNIVERSE or ["BTC/USD", "ETH/USD", "SOL/USD"]
            return [s for s in fb if s in self.markets]

    def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            return self.exchange.fetch_ticker(symbol).get("last")
        except Exception as e:
            logger.error(f"获取价格失败 {symbol}: {e}")
            return None

    def get_orderbook_imbalance(self, symbol: str, depth: int = 20) -> float:
        try:
            ob = self.exchange.fetch_order_book(symbol, depth)
            bids_vol = sum(b[1] for b in ob["bids"])
            asks_vol = sum(a[1] for a in ob["asks"])
            total = bids_vol + asks_vol
            return (bids_vol - asks_vol) / total if total > 0 else 0
        except Exception as e:
            logger.error(f"获取订单簿失败 {symbol}: {e}")
            return 0.0

    def is_black_swan(self) -> bool:
        try:
            btc = "BTC/USD" if "BTC/USD" in self.markets else "BTC/USDT"
            ohlcv = self.exchange.fetch_ohlcv(btc, timeframe="5m", limit=7)
            if not ohlcv or len(ohlcv) < 2:
                return False
            start_price = ohlcv[0][4]
            end_price = ohlcv[-1][4]
            pct = (end_price - start_price) / start_price
            if pct <= -BLACK_SWAN_THRESHOLD:
                logger.warning(f"🚨 黑天鹅：BTC 30分钟跌 {pct:.1%}")
                return True
            return False
        except Exception as e:
            logger.error(f"黑天鹅检测失败: {e}")
            return False

    def _normalize_amount(self, symbol: str, amount: float) -> Optional[float]:
        try:
            m = self.markets[symbol]
            amt = float(self.exchange.amount_to_precision(symbol, amount))
            min_amt = ((m.get("limits") or {}).get("amount") or {}).get("min")
            if min_amt and amt < min_amt:
                logger.error(f"{symbol} 数量 {amt} 低于最小 {min_amt}")
                return None
            min_cost = ((m.get("limits") or {}).get("cost") or {}).get("min")
            price = self.get_current_price(symbol)
            if min_cost and price and amt * price < min_cost:
                logger.error(f"{symbol} 名义 {amt * price:.2f} 低于最小 {min_cost}")
                return None
            return amt
        except Exception as e:
            logger.error(f"数量归一化失败 {symbol}: {e}")
            return None

    def open_spot_buy(self, symbol: str, usd_amount: float) -> dict:
        """V1.2 #1/#4: 市价买入现货，无杠杆。数量 = usd_amount / price（不乘杠杆）。"""
        if self.paper:
            return self._paper_open_buy(symbol, usd_amount)
        try:
            price = self.get_current_price(symbol)
            if not price:
                return {"status": "failed", "reason": "无法获取价格"}
            amount = self._normalize_amount(symbol, usd_amount / price)
            if not amount:
                return {"status": "failed", "reason": "数量不满足交易所限制"}
            order = self.exchange.create_market_buy_order(symbol, amount)
            entry = order.get("average") or price
            protective = self.place_protective_orders(symbol, amount, entry)
            return {
                "status": "filled",
                "order_id": order["id"],
                "entry_price": entry,
                "amount": amount,
                "protective": protective,
            }
        except Exception as e:
            logger.error(f"开仓失败 {symbol}: {e}")
            return {"status": "failed", "reason": str(e)}

    def _paper_open_buy(self, symbol: str, usd_amount: float) -> dict:
        price = self.get_current_price(symbol)
        if not price:
            return {"status": "failed", "reason": "[PAPER] 无法获取价格"}
        try:
            amount = float(self.exchange.amount_to_precision(symbol, usd_amount / price))
        except Exception:
            amount = round(usd_amount / price, 8)
        protective = self._dry_run_protective(symbol, amount, price)
        return {
            "status": "filled",
            "order_id": f"PAPER-{int(time.time())}",
            "entry_price": price,
            "amount": amount,
            "protective": protective,
            "paper": True,
        }

    def place_protective_orders(self, symbol: str, amount: float, entry: float) -> dict:
        """V1.2 #3: 交易所侧 SL/TP（现货 stop 单）+ 本地 monitor 兜底。现货无杠杆，价格百分比。"""
        if self.paper:
            return self._dry_run_protective(symbol, amount, entry)
        out = {"sl_order_id": None, "tp_order_id": None, "sl_price": None, "tp_price": None, "dry_run": False}
        sl_price = float(self.exchange.price_to_precision(symbol, entry * (1 - STOP_LOSS_PCT)))
        tp_price = float(self.exchange.price_to_precision(symbol, entry * (1 + TAKE_PROFIT_PCT)))
        try:
            sl = self.exchange.create_order(symbol, "stop", "sell", amount, sl_price,
                                             {"stopPrice": sl_price, "stop": "loss"})
            out["sl_order_id"] = sl.get("id")
        except Exception as e:
            logger.error(f"⚠️ 止损单挂单失败 {symbol}: {e}")
            send_notification(f"⚠️ {symbol} 交易所止损单失败，仅剩本地兜底监控！\n{e}", priority="critical")
        try:
            tp = self.exchange.create_order(symbol, "stop", "sell", amount, tp_price,
                                             {"stopPrice": tp_price, "stop": "entry"})
            out["tp_order_id"] = tp.get("id")
        except Exception as e:
            logger.error(f"止盈单挂单失败 {symbol}: {e}")
        out.update({"sl_price": sl_price, "tp_price": tp_price})
        return out

    def _dry_run_protective(self, symbol: str, amount: float, entry: float) -> dict:
        try:
            sl_price = float(self.exchange.price_to_precision(symbol, entry * (1 - STOP_LOSS_PCT)))
            tp_price = float(self.exchange.price_to_precision(symbol, entry * (1 + TAKE_PROFIT_PCT)))
        except Exception:
            sl_price = round(entry * (1 - STOP_LOSS_PCT), 2)
            tp_price = round(entry * (1 + TAKE_PROFIT_PCT), 2)
        return {
            "sl_order_id": None, "tp_order_id": None,
            "sl_price": sl_price, "tp_price": tp_price,
            "dry_run": True,
            "params": {"type": "stop", "side": "sell", "amount": amount,
                       "stopPrice_sl": sl_price, "stopPrice_tp": tp_price},
        }

    def cancel_open_orders(self, symbol: str) -> None:
        if self.paper:
            return
        try:
            for o in self.exchange.fetch_open_orders(symbol):
                try:
                    self.exchange.cancel_order(o["id"], symbol)
                except Exception as e:
                    logger.error(f"撤单失败 {symbol} {o.get('id')}: {e}")
        except Exception as e:
            logger.error(f"获取挂单失败 {symbol}: {e}")

    def close_spot_sell(self, symbol: str, requested_amount: float) -> dict:
        """V1.2 #2: 市价卖出现货。超卖防护：卖出量 = min(本地记录, 交易所可用余额)。"""
        if self.paper:
            return self._paper_close_sell(symbol, requested_amount)
        try:
            self.cancel_open_orders(symbol)
            base = symbol.split("/")[0]
            balance = self.exchange.fetch_balance()
            available = float((balance.get(base) or {}).get("free") or 0)
            sell_amount = min(requested_amount, available)
            if sell_amount <= 0:
                return {"status": "failed", "reason": f"超卖防护：可用 {base}={available} <= 0，无法卖出"}
            if sell_amount < requested_amount:
                logger.warning(f"⚠️ 超卖防护：{symbol} 请求 {requested_amount} 钳制为可用 {sell_amount}")
            amt = float(self.exchange.amount_to_precision(symbol, sell_amount))
            order = self.exchange.create_market_sell_order(symbol, amt)
            return {"status": "filled", "exit_price": order.get("average") or order.get("price") or 0,
                    "sold_amount": amt, "requested_amount": requested_amount, "available": available}
        except Exception as e:
            logger.error(f"平仓失败 {symbol}: {e}")
            return {"status": "failed", "reason": str(e)}

    def _paper_close_sell(self, symbol: str, requested_amount: float) -> dict:
        price = self.get_current_price(symbol) or 0
        return {"status": "filled", "exit_price": price, "sold_amount": requested_amount,
                "requested_amount": requested_amount, "available": requested_amount, "paper": True}

    def get_positions_from_balance(self, local_positions: List[dict]) -> Optional[List[dict]]:
        """V1.2 #2: 仓位状态 = fetch_balance + 本地 positions.json 对账。失败返回 None。"""
        if self.paper:
            return local_positions
        try:
            balance = self.exchange.fetch_balance()
            out = []
            for pos in local_positions:
                sym = pos["symbol"]
                base = sym.split("/")[0]
                available = float((balance.get(base) or {}).get("free") or 0)
                held = min(pos.get("amount", 0), available) if available > 0 else 0
                if held <= 0:
                    continue
                out.append({
                    "symbol": sym,
                    "amount": held,
                    "entry_price": pos.get("entry_price", 0),
                    "mark_price": self.get_current_price(sym),
                    "available_balance": available,
                    "local_recorded": pos.get("amount", 0),
                })
            return out
        except Exception as e:
            logger.error(f"获取持仓(余额对账)失败: {e}")
            return None


# ======================== 策略引擎（V1.2 现货） ========================
class CryptoEngine:
    def __init__(self, exchange: CryptoExchange, mode: str):
        self.exchange = exchange
        self.mode = mode
        self.candidates: List[str] = []
        self.logs: List[str] = []
        self.paused = False
        self.pos_fail_streak = 0
        # V1.2 #2: 本地 positions.json 是仓位真源之一
        self.local_positions: List[dict] = safe_read_json(POSITIONS_PATH, [])
        if not isinstance(self.local_positions, list):
            self.local_positions = []

    def add_log(self, message: str):
        timestamp = datetime.datetime.now(EST).strftime("%m-%d %H:%M:%S")
        self.logs.append(f"[{timestamp} EST] {message}")
        logger.info(message)
        if len(self.logs) > 300:
            self.logs = self.logs[-300:]

    def flush_state(self, positions: Optional[List[dict]] = None):
        if positions is None:
            positions = self.exchange.get_positions_from_balance(self.local_positions) or []
        atomic_write_json(POSITIONS_PATH, positions)
        atomic_write_json(LOGS_PATH, self.logs)
        atomic_write_json(HEARTBEAT_PATH, {
            "time": datetime.datetime.now(EST).isoformat(),
            "ts": time.time(),
            "paused": self.paused,
            "mode": self.mode,
            "candidates": self.candidates,
            "position_count": len(positions),
            "version": "V1.2",
        })

    def get_positions_checked(self) -> Optional[List[dict]]:
        positions = self.exchange.get_positions_from_balance(self.local_positions)
        if positions is None:
            self.pos_fail_streak += 1
            if self.pos_fail_streak == 3:
                send_notification("🚨 持仓数据连续 3 次获取失败，本地止损监控失效中（交易所侧保护单仍在）",
                                  priority="critical")
            return None
        self.pos_fail_streak = 0
        return positions

    def scan_candidates(self):
        self.add_log("🔍 开始币圈扫描 (现货 -USD)...")
        symbols = self.exchange.get_top_symbols(SCAN_TOP_SYMBOLS)
        final = []
        for sym in symbols:
            imbalance = self.exchange.get_orderbook_imbalance(sym)
            if imbalance > 0.1:
                final.append(sym)
            if len(final) >= TOP_CANDIDATES:
                break
        self.candidates = final
        self.add_log(f"✅ 币圈候选: {', '.join(self.candidates) if self.candidates else '（无）'}")
        if self.candidates:
            send_notification(f"🪙 币圈候选: {', '.join(self.candidates)}")

    def check_and_buy(self):
        if self.paused:
            return
        if not self.candidates:
            return
        if self.exchange.is_black_swan():
            send_notification("🚨 黑天鹅警报：BTC 急跌，暂停开仓", priority="critical")
            return
        positions = self.get_positions_checked()
        if positions is None:
            self.add_log("⚠️ 持仓未知，跳过本轮开仓（安全优先）")
            return
        if len(positions) >= MAX_POSITIONS:
            return
        held = {p["symbol"] for p in positions}
        for sym in self.candidates:
            if sym in held:
                continue
            imbalance = self.exchange.get_orderbook_imbalance(sym)
            if imbalance <= 0.1:
                self.add_log(f"⏭️ {sym} 买入时刻信号消失 (imb={imbalance:.2f})，跳过")
                continue
            self.add_log(f"🚀 开仓候选 {sym} (imb={imbalance:.2f})")
            order = self.exchange.open_spot_buy(sym, CAPITAL_PER_TRADE)
            if order["status"] == "filled":
                prot = order.get("protective", {})
                msg = (f"✅ 买入 {sym}\n入场价: ${order['entry_price']:.4f}\n"
                       f"名义: ${CAPITAL_PER_TRADE} | 数量: {order['amount']}\n"
                       f"交易所SL: {prot.get('sl_price')} TP: {prot.get('tp_price')}")
                self.add_log(msg.replace("\n", " | "))
                send_notification(msg, priority="critical")
                # V1.2 #2: 写入本地 positions.json
                self.local_positions.append({
                    "symbol": sym,
                    "amount": order["amount"],
                    "entry_price": order["entry_price"],
                    "order_id": order.get("order_id"),
                    "protective": prot,
                    "opened_at": datetime.datetime.now(EST).isoformat(),
                })
                atomic_write_json(POSITIONS_PATH, self.local_positions)
                append_journal({"action": "open_spot_buy", "symbol": sym,
                                "entry_price": order["entry_price"], "amount": order["amount"],
                                "usd_amount": CAPITAL_PER_TRADE,
                                "signal": {"orderbook_imbalance": round(imbalance, 4)},
                                "protective": prot, "mode": self.mode})
            else:
                self.add_log(f"❌ 开仓失败 {sym}: {order.get('reason', '未知')}")
            break

    def monitor_positions(self):
        """V1.2 #3/#4: 本地兜底监控。现货无杠杆，价格百分比即盈亏比。"""
        positions = self.get_positions_checked()
        if positions is None:
            return
        for pos in positions:
            sym = pos["symbol"]
            current_price = pos.get("mark_price") or self.exchange.get_current_price(sym)
            if not current_price or not pos["entry_price"]:
                continue
            # V1.2 #4: 价格百分比（无杠杆）
            pct = (current_price - pos["entry_price"]) / pos["entry_price"]
            action = None
            if pct <= -STOP_LOSS_PCT:
                action = "止损(本地兜底)"
            elif pct >= TAKE_PROFIT_PCT:
                action = "止盈(本地兜底)"
            if action:
                self._close_position(pos, current_price, pct, action)
        self.flush_state(positions)

    def _close_position(self, pos: dict, current_price: float, pct: float, reason: str):
        # V1.2 #2: 超卖防护在 close_spot_sell 内部
        order = self.exchange.close_spot_sell(pos["symbol"], pos["amount"])
        if order["status"] == "filled":
            exit_price = order.get("exit_price") or current_price
            sold = order.get("sold_amount", pos["amount"])
            msg = (f"🔴 {reason} {pos['symbol']}\n"
                   f"入场: ${pos['entry_price']:.4f} 出场: ${exit_price:.4f}\n"
                   f"价格变动: {pct:.1%} | 卖出量: {sold}")
            self.add_log(msg.replace("\n", " | "))
            send_notification(msg, priority="critical")
            # V1.2 #2: 从本地 positions.json 移除
            self.local_positions = [p for p in self.local_positions if p.get("symbol") != pos["symbol"]]
            atomic_write_json(POSITIONS_PATH, self.local_positions)
            append_journal({"action": "close_spot_sell", "symbol": pos["symbol"], "reason": reason,
                            "entry_price": pos["entry_price"], "exit_price": exit_price,
                            "amount": sold, "price_pct": round(pct, 4), "mode": self.mode})
        else:
            self.add_log(f"❌ 平仓失败 {pos['symbol']}: {order.get('reason', '未知')}")
            send_notification(f"🚨 平仓失败 {pos['symbol']}: {order.get('reason')}", priority="critical")

    def emergency_close_all(self):
        self.add_log("🆘 紧急平仓指令收到")
        positions = self.get_positions_checked()
        if positions is None:
            send_notification("🚨 紧急平仓：持仓数据获取失败，请立即手动处理！", priority="critical")
            return
        for pos in positions:
            price = self.exchange.get_current_price(pos["symbol"]) or pos["entry_price"]
            pct = ((price - pos["entry_price"]) / pos["entry_price"]) if pos["entry_price"] else 0
            self._close_position(pos, price, pct, "紧急平仓")
        self.add_log("🆘 紧急平仓完成")
        self.flush_state()

    def handle_commands(self):
        for cmd in poll_commands():
            name = cmd.get("cmd", "")
            self.add_log(f"📥 指令: {name}")
            if name == "emergency_close_all":
                self.emergency_close_all()
            elif name == "pause":
                self.paused = True
                self.add_log("⏸️ 已暂停开仓（持仓监控继续）")
                send_notification("⏸️ Aether Crypto V1.2 已暂停开仓")
            elif name == "resume":
                self.paused = False
                self.add_log("▶️ 已恢复开仓")
                send_notification("▶️ Aether Crypto V1.2 已恢复开仓")
            elif name == "scan_now":
                self.scan_candidates()
            elif name == "close" and cmd.get("symbol"):
                positions = self.get_positions_checked() or []
                for pos in positions:
                    if pos["symbol"] == cmd["symbol"]:
                        price = self.exchange.get_current_price(pos["symbol"]) or pos["entry_price"]
                        pct = ((price - pos["entry_price"]) / pos["entry_price"]) if pos["entry_price"] else 0
                        self._close_position(pos, price, pct, "手动平仓")
            else:
                self.add_log(f"⚠️ 未知指令: {name}")


# ======================== Daemon 主循环 ========================
class CryptoDaemon:
    def __init__(self):
        # V1.2 #5: 合规断言先行
        assert_compliance()
        # V1.2 #6: 档位解析 + live 双闸
        self.mode = resolve_mode()
        self.exchange = CryptoExchange(self.mode)
        self.engine = CryptoEngine(self.exchange, self.mode)
        self.running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info("🛑 收到终止信号，准备优雅退出...")
        self.running = False

    def run(self):
        banner = (
            f"🚀 Aether Nexus Crypto Daemon V1.2 启动 [{self.mode}]\n"
            f"   交易所: {EXCHANGE_ID} | 宇宙: {SPOT_UNIVERSE}\n"
            f"   SL: {STOP_LOSS_PCT} (价格%) | TP: {TAKE_PROFIT_PCT} (价格%) | 无杠杆\n"
            f"   每笔名义: ${CAPITAL_PER_TRADE} | 最大持仓: {MAX_POSITIONS} | 总敞口上限: ${MAX_TOTAL_EXPOSURE}"
        )
        logger.info(banner)
        self.engine.add_log(f"🟢 Crypto Daemon V1.2 启动 [{self.mode}]")
        send_notification(f"🟢 Aether Nexus Crypto V1.2 已启动 [{self.mode}]")
        self.engine.flush_state()

        last_scan = 0.0
        last_monitor = 0.0
        last_buy_check = 0.0

        while self.running:
            try:
                self.engine.handle_commands()
                now = time.time()
                if now - last_scan >= SCAN_INTERVAL:
                    self.engine.scan_candidates()
                    last_scan = now
                if now - last_buy_check >= BUY_CHECK_INTERVAL:
                    self.engine.check_and_buy()
                    last_buy_check = now
                if now - last_monitor >= MONITOR_INTERVAL:
                    self.engine.monitor_positions()
                    last_monitor = now
                time.sleep(CMD_POLL_INTERVAL)
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                self.engine.add_log(f"⚠️ 主循环异常: {e}")
                time.sleep(30)

        self.engine.add_log("🛑 Daemon 停止（持仓保留，交易所侧保护单仍生效）")
        self.engine.flush_state()
        send_notification("🛑 Aether Crypto Daemon V1.2 已停止。持仓未平，交易所侧 SL/TP 仍在。",
                          priority="critical")
        logger.info("已退出")


if __name__ == "__main__":
    CryptoDaemon().run()
