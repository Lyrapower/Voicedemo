#!/usr/bin/env python3
"""
Aether Nexus Crypto V1.1 — Shared Layer
配置、原子文件IO、通知（完全独立，不依赖美股版）

V1.1 changes:
- 策略参数全部走 env（V1.0 硬编码在代码里）
- Telegram 改为 plain Bot API（去掉 telebot 依赖 + 裸 except）
- 通知失败不再静默；增加 NOTIFY_COOLDOWN 防止报警风暴
- 新增 heartbeat / journal 路径常量（daemon 写，dashboard 读）
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

# ======================== 交易所配置 ========================
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance")  # binance / bybit / okx
EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
EXCHANGE_SECRET_KEY = os.getenv("EXCHANGE_SECRET_KEY", "")
EXCHANGE_TESTNET = os.getenv("EXCHANGE_TESTNET", "true").lower() == "true"

# ======================== 通知 ========================
PUSHOVER_USER = os.getenv("PUSHOVER_USER", "")
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NOTIFY_COOLDOWN = float(os.getenv("NOTIFY_COOLDOWN", "60"))  # 同文本通知最小间隔（秒）

# ======================== 策略参数（V1.1: env 可调） ========================
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
CAPITAL_PER_TRADE = float(os.getenv("CAPITAL_PER_TRADE", "500.0"))   # 每笔保证金 (USDT)
MAX_LEVERAGE = int(os.getenv("MAX_LEVERAGE", "2"))

# 注意语义：STOP_LOSS_PCT / TAKE_PROFIT_PCT 是【保证金盈亏比例 (ROE)】，不是价格变动。
# 2× 杠杆下 STOP_LOSS_PCT=0.10 等价于价格反向移动 5%。
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.10"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.30"))
BLACK_SWAN_THRESHOLD = float(os.getenv("BLACK_SWAN_THRESHOLD", "0.05"))  # BTC 30min 跌幅

SCAN_TOP_SYMBOLS = int(os.getenv("SCAN_TOP_SYMBOLS", "30"))
TOP_CANDIDATES = int(os.getenv("TOP_CANDIDATES", "3"))
MIN_QUOTE_VOLUME_USDT = float(os.getenv("MIN_QUOTE_VOLUME_USDT", "50000000"))  # 24h 成交额下限

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
    """V1.1: 每笔开/平仓的完整记录，事后复盘和策略期望值验证的依据。"""
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


# ======================== 通知模块 ========================
_NOTIFY_LAST: dict = {}  # message-key -> last sent ts，防报警风暴


def _should_send(message: str, priority: str) -> bool:
    if priority == "critical":
        return True  # critical 永不抑制
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
    """V1.1: plain Bot API，去掉 telebot 依赖和裸 except pass。"""
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
