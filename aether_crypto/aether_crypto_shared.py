#!/usr/bin/env python3
"""
Aether Nexus Crypto V1.2 — Shared Layer (现货合规版)
配置、原子文件IO、通知（独立，不依赖美股版）

V1.2 changes vs V1.1:
- 杠杆语义全拆：无 defaultType=swap / set_leverage / MAX_LEVERAGE；宇宙改 -USD 现货对
- 持仓=余额：仓位状态来自 fetch_balance + 本地 positions.json 对账（现货无 fetch_positions）
- 止损/止盈：STOP_LOSS_PCT/TAKE_PROFIT_PCT 即价格百分比（无杠杆换算）
- 合规断言：BLOCKED_EXCHANGES={"bybit","binance"}，命中启动即死
- live 双闸：LIVE_TRADING=false 默认 + LIVE_ACK=YES_I_AUTHORIZED_LIVE 双键
- 三档模式：PAPER / SANDBOX / LIVE，启动 banner 打印档位
- 信号层不动：开仓信号仍订单簿不平衡（策略轮再改）
- 通知信道：Pushover/Telegram 代码保留，默认空 key 即静默
- registry：capability aether.crypto.spot_v12，daemon 无监听端口
"""

import os
import json
import time
import tempfile
import datetime
import logging
import requests
import pytz
from dotenv import load_dotenv

load_dotenv()

# ======================== 路径 ========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "state")
CMD_DIR = os.path.join(BASE_DIR, "commands")
os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(CMD_DIR, exist_ok=True)

POSITIONS_PATH = os.path.join(STATE_DIR, "positions.json")
LOGS_PATH = os.path.join(STATE_DIR, "logs.json")
HEARTBEAT_PATH = os.path.join(STATE_DIR, "heartbeat.json")
JOURNAL_PATH = os.path.join(STATE_DIR, "trade_journal.json")

# ======================== 交易档位（V1.2 三档） ========================
# TRADING_MODE: paper | sandbox | live
#   paper   — 不连交易所，本地构造订单全字段日志（验收 B/D 默认档）
#   sandbox — coinbaseexchange + set_sandbox_mode(True)，真实沙盒 API
#   live    — 须同时满足 LIVE_TRADING=true 且 LIVE_ACK=YES_I_AUTHORIZED_LIVE
TRADING_MODE = os.getenv("TRADING_MODE", "paper").lower().strip()

# ======================== 交易所配置（V1.2: 默认 coinbaseexchange，bybit 铲除） ========================
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "coinbaseexchange")  # coinbaseexchange / kraken
EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
EXCHANGE_SECRET_KEY = os.getenv("EXCHANGE_SECRET_KEY", "")
EXCHANGE_PASSPHRASE = os.getenv("EXCHANGE_PASSPHRASE", "")  # coinbaseexchange 需要 passphrase

# V1.2 #5 合规断言：命中即启动死闸
BLOCKED_EXCHANGES = set(os.getenv("BLOCKED_EXCHANGES", "bybit,binance").split(","))
BLOCKED_EXCHANGES = {x.strip().lower() for x in BLOCKED_EXCHANGES if x.strip()}

# ======================== live 双闸（V1.2 #6） ========================
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
LIVE_ACK = os.getenv("LIVE_ACK", "").strip()
LIVE_ACK_REQUIRED = "YES_I_AUTHORIZED_LIVE"

# ======================== 通知（V1.2 #8: 默认空 key 即静默，留删待 Lyra） ========================
PUSHOVER_USER = os.getenv("PUSHOVER_USER", "")
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NOTIFY_COOLDOWN = float(os.getenv("NOTIFY_COOLDOWN", "60"))

# ======================== 策略参数（V1.2 #4: 无杠杆，即价格百分比） ========================
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
CAPITAL_PER_TRADE = float(os.getenv("CAPITAL_PER_TRADE", "500.0"))   # 每笔名义金额 (USD)
MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE", "0.0"))   # 总敞口上限，live 档零默认必显式

# V1.2 语义：STOP_LOSS_PCT / TAKE_PROFIT_PCT 是【价格百分比】，不是 ROE。
# 现货无杠杆，价格跌 5% = 仓位亏 5%。默认 SL 0.05 / TP 0.15（现货波动档，Lyra 可调）。
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.05"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.15"))
BLACK_SWAN_THRESHOLD = float(os.getenv("BLACK_SWAN_THRESHOLD", "0.05"))  # BTC 30min 跌幅

# V1.2 #1: 现货宇宙 = -USD 现货对（默认 BTC/ETH/SOL，env SPOT_UNIVERSE 可扩）
SPOT_UNIVERSE_DEFAULT = "BTC/USD,ETH/USD,SOL/USD"
SPOT_UNIVERSE = [s.strip() for s in os.getenv("SPOT_UNIVERSE", SPOT_UNIVERSE_DEFAULT).split(",") if s.strip()]

SCAN_TOP_SYMBOLS = int(os.getenv("SCAN_TOP_SYMBOLS", "30"))
TOP_CANDIDATES = int(os.getenv("TOP_CANDIDATES", "3"))
MIN_QUOTE_VOLUME_USD = float(os.getenv("MIN_QUOTE_VOLUME_USD", "50000000"))  # 24h 成交额下限（USD）

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "3600"))
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "60"))
BUY_CHECK_INTERVAL = int(os.getenv("BUY_CHECK_INTERVAL", "300"))
CMD_POLL_INTERVAL = int(os.getenv("CMD_POLL_INTERVAL", "10"))

# 时区
UTC = pytz.UTC
EST = pytz.timezone("US/Eastern")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(STATE_DIR, "crypto_daemon.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("AetherCrypto")


# ======================== 档位解析（V1.2 #6: 启动 banner 用） ========================
def resolve_mode() -> str:
    """返回 PAPER / SANDBOX / LIVE，并校验 live 双闸。live 不满足 → 抛 SystemExit。"""
    mode = TRADING_MODE
    if mode == "live":
        if not (LIVE_TRADING and LIVE_ACK == LIVE_ACK_REQUIRED):
            raise SystemExit(
                f"❌ LIVE 档启动被拒：需同时满足 LIVE_TRADING=true 且 LIVE_ACK={LIVE_ACK_REQUIRED}。"
                f"当前 LIVE_TRADING={LIVE_TRADING}, LIVE_ACK={LIVE_ACK!r}"
            )
        return "LIVE"
    if mode == "sandbox":
        return "SANDBOX"
    return "PAPER"


def assert_compliance() -> None:
    """V1.2 #5: EXCHANGE_ID 命中 BLOCKED_EXCHANGES → 启动即死。"""
    if EXCHANGE_ID.lower() in BLOCKED_EXCHANGES:
        raise SystemExit(
            f"❌ 合规断言失败：EXCHANGE_ID={EXCHANGE_ID!r} 命中 BLOCKED_EXCHANGES={sorted(BLOCKED_EXCHANGES)}。"
            f"V1.2 禁止 bybit/binance，启动即死。"
        )


# ======================== 原子文件 IO ========================
def atomic_write_json(filepath: str, data):
    tmp_path = None
    try:
        dir_name = os.path.dirname(filepath)
        with tempfile.NamedTemporaryFile(mode="w", dir=dir_name, suffix=".tmp", delete=False) as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            tmp_path = f.name
        os.replace(tmp_path, filepath)
    except Exception as e:
        logger.error(f"原子写入失败 {filepath}: {e}")
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def safe_read_json(filepath: str, default=None):
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def append_journal(entry: dict, keep: int = 2000):
    journal = safe_read_json(JOURNAL_PATH, [])
    if not isinstance(journal, list):
        journal = []
    entry = {"time": datetime.datetime.now(EST).isoformat(), **entry}
    journal.append(entry)
    atomic_write_json(JOURNAL_PATH, journal[-keep:])


def send_command(cmd_name: str, payload: dict = None):
    filepath = os.path.join(CMD_DIR, f"{cmd_name}_{int(time.time())}.cmd")
    data = {"cmd": cmd_name, "time": datetime.datetime.now(EST).isoformat()}
    if payload:
        data.update(payload)
    atomic_write_json(filepath, data)


def poll_commands() -> list:
    commands = []
    try:
        for f in sorted(os.listdir(CMD_DIR)):
            if f.endswith(".cmd"):
                filepath = os.path.join(CMD_DIR, f)
                data = safe_read_json(filepath)
                if data:
                    commands.append(data)
                try:
                    os.unlink(filepath)
                except OSError as e:
                    logger.error(f"指令文件删除失败 {f}: {e}")
    except Exception as e:
        logger.error(f"指令轮询失败: {e}")
    return commands


# ======================== 通知模块（V1.2 #8: 默认空 key 即静默） ========================
_NOTIFY_LAST: dict = {}


def _should_send(message: str, priority: str) -> bool:
    if priority == "critical":
        return True
    key = message[:80]
    now = time.time()
    if now - _NOTIFY_LAST.get(key, 0) < NOTIFY_COOLDOWN:
        return False
    _NOTIFY_LAST[key] = now
    return True


def send_notification(message: str, priority: str = "normal"):
    if not _should_send(message, priority):
        logger.debug(f"通知抑制 (cooldown): {message[:60]}")
        return
    if not (PUSHOVER_USER and PUSHOVER_TOKEN) and not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        # V1.2 #8: 无任何通知 key 即静默（不报错，留删待 Lyra）
        logger.debug(f"通知静默 (无 key): {message[:60]}")
        return
    if PUSHOVER_USER and PUSHOVER_TOKEN:
        if priority == "critical":
            if _pushover(message, critical=True):
                return
            if _telegram("🚨 [CRITICAL FALLBACK]\n" + message):
                return
            logger.error(f"🚨 CRITICAL 通知发送全部失败: {message[:120]}")
            return
        if _pushover(message):
            return
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
        if resp.status_code != 200:
            logger.error(f"Pushover 失败: HTTP {resp.status_code} {resp.text[:120]}")
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Pushover 异常: {e}")
        return False


def _telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message[:4096]},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"Telegram 失败: HTTP {resp.status_code} {resp.text[:120]}")
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram 异常: {e}")
        return False
