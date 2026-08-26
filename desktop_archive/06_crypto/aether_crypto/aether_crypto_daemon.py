#!/usr/bin/env python3
"""
Aether Nexus Crypto V1.1 — Daemon
7×24 加密货币永续合约自动交易引擎

V1.1 critical fixes（V1.0 不可接真钱，testnet 配置本身也是坏的）:
1. Testnet 改用 ccxt 标准 set_sandbox_mode()（V1.0 的 config["test"]=True 无效，
   EXCHANGE_TESTNET=true 时实际静默连实盘）
2. 锁定永续市场 defaultType=swap + load_markets，候选只保留 :USDT 永续
   （V1.0 现货/永续混用，set_leverage/fetch_positions 在现货模式下不工作）
3. 所有平仓单 reduceOnly=True（V1.0 裸市价卖单，size 偏差会反向开出空头）
4. 开仓成功后立即在【交易所侧】挂止损/止盈单（V1.0 止损只活在 Python 进程里，
   daemon 挂掉 = 持仓裸奔）；本地 monitor 降级为兜底+对账
5. 下单数量走 amount_to_precision + 最小名义校验（V1.0 会被 LOT_SIZE/MIN_NOTIONAL 拒单）
6. 主循环接入 poll_commands：emergency_close_all / pause / resume / scan_now 可达
7. 每周期写出 positions.json / logs.json / heartbeat.json（V1.0 dashboard 读的文件
   daemon 从未写过）
8. 裸 except 全部消灭；get_positions 连续失败发 critical（静默返回 [] 等于止损失效）
9. 优雅停机：signal 只置 running=False，主循环自然退出并 flush 状态 + 通知
10. 黑天鹅窗口修正为真实 30 分钟（7 根 5m）；移除 price<1 过滤（币价绝对值无信息量，
    且与 fallback 列表自相矛盾），改用 24h 成交额下限

仍然保留的已知限制（V1.2 策略轮再处理）:
- 开仓信号仍然只有订单簿不平衡（已改为买入时刻复查，但本质仍是 BUY-bias，无趋势过滤）
"""

import time
import datetime
import signal
import ccxt
from typing import List, Optional, Dict

from aether_crypto_shared import *


# ======================== 交易所接口 ========================
class CryptoExchange:
    def __init__(self):
        exchange_class = getattr(ccxt, EXCHANGE_ID)
        self.exchange = exchange_class({
            "apiKey": EXCHANGE_API_KEY,
            "secret": EXCHANGE_SECRET_KEY,
            "enableRateLimit": True,
            # V1.1 fix#2: 锁定永续。binance 下等价于 binanceusdm 行为。
            "options": {"defaultType": "swap"},
        })
        # V1.1 fix#1: ccxt 标准沙盒模式。V1.0 的 config["test"]=True 是无效字段。
        if EXCHANGE_TESTNET:
            self.exchange.set_sandbox_mode(True)
        self.markets = self.exchange.load_markets()
        mode = "TESTNET" if EXCHANGE_TESTNET else "⚠️ LIVE"
        logger.info(f"交易所 {EXCHANGE_ID} 连接成功 [{mode}] markets={len(self.markets)}")
        if not EXCHANGE_TESTNET:
            send_notification(f"⚠️ Aether Crypto 以 LIVE 模式连接 {EXCHANGE_ID}", priority="critical")

    # ---------- 市场数据 ----------
    def get_top_symbols(self, limit: int = 30) -> List[str]:
        """USDT 线性永续，按 24h 成交额排序。V1.1: 只保留 swap，剔除现货。"""
        try:
            tickers = self.exchange.fetch_tickers()
            perps = []
            for sym, t in tickers.items():
                m = self.markets.get(sym)
                if not m or not m.get("swap") or not m.get("linear") or m.get("quote") != "USDT":
                    continue
                qv = t.get("quoteVolume") or 0
                if qv < MIN_QUOTE_VOLUME_USDT:
                    continue
                perps.append((sym, qv))
            perps.sort(key=lambda x: -x[1])
            return [s for s, _ in perps[:limit]]
        except Exception as e:
            logger.error(f"获取交易对失败: {e}")
            # V1.1: fallback 也必须是永续符号（V1.0 的 fallback 全是现货）
            fb = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
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
        """V1.1: 7 根 5m = 真实 30 分钟窗口（V1.0 的 6 根只有 25 分钟）。"""
        try:
            btc = "BTC/USDT:USDT" if "BTC/USDT:USDT" in self.markets else "BTC/USDT"
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
            return False  # 数据失败时不阻断，但已记录

    # ---------- 下单 ----------
    def _normalize_amount(self, symbol: str, amount: float) -> Optional[float]:
        """V1.1 fix#5: 精度 + 最小数量/名义校验，避免 LOT_SIZE / MIN_NOTIONAL 拒单。"""
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

    def open_long(self, symbol: str, usdt_amount: float, leverage: int = 2) -> dict:
        """市价开多 + 立即挂交易所侧止损/止盈（fix#4）。"""
        try:
            try:
                self.exchange.set_leverage(leverage, symbol)
            except Exception as e:
                # 部分交易所重复设置同杠杆会报错，记录但不阻断
                logger.warning(f"set_leverage {symbol}: {e}")
            price = self.get_current_price(symbol)
            if not price:
                return {"status": "failed", "reason": "无法获取价格"}
            amount = self._normalize_amount(symbol, (usdt_amount * leverage) / price)
            if not amount:
                return {"status": "failed", "reason": "数量不满足交易所限制"}
            order = self.exchange.create_market_buy_order(symbol, amount)
            entry = order.get("average") or price
            protective = self.place_protective_orders(symbol, amount, entry, leverage)
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

    def place_protective_orders(self, symbol: str, amount: float, entry: float, leverage: int) -> dict:
        """交易所侧 SL/TP，daemon 挂掉时持仓仍受保护。两单均 reduceOnly。

        SL/TP 价格由 ROE 阈值换算：价格变动 = ROE 阈值 / 杠杆。
        """
        out = {"sl_order_id": None, "tp_order_id": None}
        sl_price = float(self.exchange.price_to_precision(symbol, entry * (1 - STOP_LOSS_PCT / leverage)))
        tp_price = float(self.exchange.price_to_precision(symbol, entry * (1 + TAKE_PROFIT_PCT / leverage)))
        try:
            sl = self.exchange.create_order(symbol, "market", "sell", amount, None,
                                            {"stopLossPrice": sl_price, "reduceOnly": True})
            out["sl_order_id"] = sl.get("id")
        except Exception as e:
            logger.error(f"⚠️ 止损单挂单失败 {symbol}: {e}")
            send_notification(f"⚠️ {symbol} 交易所止损单失败，仅剩本地兜底监控！\n{e}", priority="critical")
        try:
            tp = self.exchange.create_order(symbol, "market", "sell", amount, None,
                                            {"takeProfitPrice": tp_price, "reduceOnly": True})
            out["tp_order_id"] = tp.get("id")
        except Exception as e:
            logger.error(f"止盈单挂单失败 {symbol}: {e}")
        out.update({"sl_price": sl_price, "tp_price": tp_price})
        return out

    def cancel_open_orders(self, symbol: str) -> None:
        """手动/本地平仓前撤掉遗留的保护单，避免平仓后 reduceOnly 单变成幽灵单。"""
        try:
            for o in self.exchange.fetch_open_orders(symbol):
                try:
                    self.exchange.cancel_order(o["id"], symbol)
                except Exception as e:
                    logger.error(f"撤单失败 {symbol} {o.get('id')}: {e}")
        except Exception as e:
            logger.error(f"获取挂单失败 {symbol}: {e}")

    def close_long(self, symbol: str, amount: float) -> dict:
        """市价平多。V1.1 fix#3: reduceOnly，杜绝超卖反向开空。"""
        try:
            self.cancel_open_orders(symbol)
            amt = float(self.exchange.amount_to_precision(symbol, amount))
            order = self.exchange.create_market_sell_order(symbol, amt, params={"reduceOnly": True})
            return {"status": "filled", "exit_price": order.get("average") or order.get("price") or 0}
        except Exception as e:
            logger.error(f"平仓失败 {symbol}: {e}")
            return {"status": "failed", "reason": str(e)}

    def get_positions(self) -> Optional[List[dict]]:
        """V1.1: 失败返回 None 而不是 []。
        （V1.0 异常静默返回空列表，monitor 会误判为无持仓 -> 止损失效）"""
        try:
            positions = self.exchange.fetch_positions()
            active = []
            for p in positions:
                contracts = float(p.get("contracts") or 0)
                if contracts > 0:
                    active.append({
                        "symbol": p["symbol"],
                        "size": contracts,
                        "entry_price": float(p.get("entryPrice") or 0),
                        "leverage": int(float(p.get("leverage") or 1)),
                        "unrealized_pnl": float(p.get("unrealizedPnl") or 0),
                        "mark_price": float(p.get("markPrice") or 0) or None,
                    })
            return active
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return None


# ======================== 策略引擎 ========================
class CryptoEngine:
    def __init__(self, exchange: CryptoExchange):
        self.exchange = exchange
        self.candidates: List[str] = []
        self.logs: List[str] = []
        self.paused = False
        self.pos_fail_streak = 0

    def add_log(self, message: str):
        timestamp = datetime.datetime.now(EST).strftime("%m-%d %H:%M:%S")
        self.logs.append(f"[{timestamp} EST] {message}")
        logger.info(message)
        if len(self.logs) > 300:
            self.logs = self.logs[-300:]

    # ---------- 状态落盘（fix#7: dashboard 终于有东西可读） ----------
    def flush_state(self, positions: Optional[List[dict]] = None):
        if positions is None:
            positions = self.exchange.get_positions() or []
        atomic_write_json(POSITIONS_PATH, positions)
        atomic_write_json(LOGS_PATH, self.logs)
        atomic_write_json(HEARTBEAT_PATH, {
            "time": datetime.datetime.now(EST).isoformat(),
            "ts": time.time(),
            "paused": self.paused,
            "testnet": EXCHANGE_TESTNET,
            "candidates": self.candidates,
            "position_count": len(positions),
        })

    def get_positions_checked(self) -> Optional[List[dict]]:
        """持仓获取 + 连续失败升级为 critical（fix#8）。"""
        positions = self.exchange.get_positions()
        if positions is None:
            self.pos_fail_streak += 1
            if self.pos_fail_streak == 3:
                send_notification("🚨 持仓数据连续 3 次获取失败，本地止损监控失效中（交易所侧保护单仍在）",
                                  priority="critical")
            return None
        self.pos_fail_streak = 0
        return positions

    # ---------- 扫描 / 开仓 / 监控 ----------
    def scan_candidates(self):
        self.add_log("🔍 开始币圈扫描...")
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
            # V1.1: 买入时刻复查信号（V1.0 用的是最长 1 小时前的扫描快照）
            imbalance = self.exchange.get_orderbook_imbalance(sym)
            if imbalance <= 0.1:
                self.add_log(f"⏭️ {sym} 买入时刻信号消失 (imb={imbalance:.2f})，跳过")
                continue
            self.add_log(f"🚀 开仓候选 {sym} (imb={imbalance:.2f})")
            order = self.exchange.open_long(sym, CAPITAL_PER_TRADE, MAX_LEVERAGE)
            if order["status"] == "filled":
                prot = order.get("protective", {})
                msg = (f"✅ 开多 {sym}\n入场价: ${order['entry_price']:.4f}\n"
                       f"保证金: ${CAPITAL_PER_TRADE} | 杠杆: {MAX_LEVERAGE}×\n"
                       f"交易所SL: {prot.get('sl_price')} TP: {prot.get('tp_price')}")
                self.add_log(msg.replace("\n", " | "))
                send_notification(msg, priority="critical")
                append_journal({"action": "open_long", "symbol": sym,
                                "entry_price": order["entry_price"], "amount": order["amount"],
                                "leverage": MAX_LEVERAGE, "margin_usdt": CAPITAL_PER_TRADE,
                                "signal": {"orderbook_imbalance": round(imbalance, 4)},
                                "protective": prot})
            else:
                self.add_log(f"❌ 开仓失败 {sym}: {order.get('reason', '未知')}")
            break

    def monitor_positions(self):
        """本地兜底监控。主保护是交易所侧 SL/TP 单；这里负责对账和异常情况。"""
        positions = self.get_positions_checked()
        if positions is None:
            return
        for pos in positions:
            sym = pos["symbol"]
            current_price = pos.get("mark_price") or self.exchange.get_current_price(sym)
            if not current_price or not pos["entry_price"]:
                continue
            # ROE（保证金盈亏比例）= 价格变动 × 杠杆
            roe = (current_price - pos["entry_price"]) / pos["entry_price"] * pos["leverage"]
            action = None
            if roe <= -STOP_LOSS_PCT:
                action = "止损(本地兜底)"
            elif roe >= TAKE_PROFIT_PCT:
                action = "止盈(本地兜底)"
            if action:
                self._close_position(pos, current_price, roe, action)
        self.flush_state(positions)

    def _close_position(self, pos: dict, current_price: float, roe: float, reason: str):
        order = self.exchange.close_long(pos["symbol"], pos["size"])
        if order["status"] == "filled":
            exit_price = order.get("exit_price") or current_price
            msg = (f"🔴 {reason} {pos['symbol']}\n"
                   f"入场: ${pos['entry_price']:.4f} 出场: ${exit_price:.4f}\n"
                   f"ROE: {roe:.1%} | uPnL(交易所): ${pos.get('unrealized_pnl', 0):.2f}")
            self.add_log(msg.replace("\n", " | "))
            send_notification(msg, priority="critical")
            append_journal({"action": "close_long", "symbol": pos["symbol"], "reason": reason,
                            "entry_price": pos["entry_price"], "exit_price": exit_price,
                            "size": pos["size"], "roe": round(roe, 4),
                            "unrealized_pnl_at_close": pos.get("unrealized_pnl")})
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
            roe = ((price - pos["entry_price"]) / pos["entry_price"] * pos["leverage"]) if pos["entry_price"] else 0
            self._close_position(pos, price, roe, "紧急平仓")
        self.add_log("🆘 紧急平仓完成")
        self.flush_state()

    # ---------- 指令处理（fix#6: V1.0 的指令系统从未被消费） ----------
    def handle_commands(self):
        for cmd in poll_commands():
            name = cmd.get("cmd", "")
            self.add_log(f"📥 指令: {name}")
            if name == "emergency_close_all":
                self.emergency_close_all()
            elif name == "pause":
                self.paused = True
                self.add_log("⏸️ 已暂停开仓（持仓监控继续）")
                send_notification("⏸️ Aether Crypto 已暂停开仓")
            elif name == "resume":
                self.paused = False
                self.add_log("▶️ 已恢复开仓")
                send_notification("▶️ Aether Crypto 已恢复开仓")
            elif name == "scan_now":
                self.scan_candidates()
            elif name == "close" and cmd.get("symbol"):
                positions = self.get_positions_checked() or []
                for pos in positions:
                    if pos["symbol"] == cmd["symbol"]:
                        price = self.exchange.get_current_price(pos["symbol"]) or pos["entry_price"]
                        roe = ((price - pos["entry_price"]) / pos["entry_price"] * pos["leverage"]) if pos["entry_price"] else 0
                        self._close_position(pos, price, roe, "手动平仓")
            else:
                self.add_log(f"⚠️ 未知指令: {name}")


# ======================== Daemon 主循环 ========================
class CryptoDaemon:
    def __init__(self):
        self.exchange = CryptoExchange()
        self.engine = CryptoEngine(self.exchange)
        self.running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        # V1.1 fix#9: 不在 signal handler 里 sys.exit；让主循环自然收尾
        logger.info("🛑 收到终止信号，准备优雅退出...")
        self.running = False

    def run(self):
        mode = "TESTNET" if EXCHANGE_TESTNET else "⚠️ LIVE"
        logger.info(f"🚀 Aether Nexus Crypto Daemon V1.1 启动 [{mode}]")
        self.engine.add_log(f"🟢 Crypto Daemon V1.1 启动 [{mode}]")
        send_notification(f"🟢 Aether Nexus Crypto V1.1 已启动 [{mode}]")
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
                    self.engine.monitor_positions()  # 内部含 flush_state
                    last_monitor = now
                time.sleep(CMD_POLL_INTERVAL)
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                self.engine.add_log(f"⚠️ 主循环异常: {e}")
                time.sleep(30)

        # 优雅停机
        self.engine.add_log("🛑 Daemon 停止（持仓保留，交易所侧保护单仍生效）")
        self.engine.flush_state()
        send_notification("🛑 Aether Crypto Daemon 已停止。持仓未平，交易所侧 SL/TP 仍在。",
                          priority="critical")
        logger.info("已退出")


if __name__ == "__main__":
    CryptoDaemon().run()
