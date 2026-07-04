#!/usr/bin/env python3
"""
Aether Nexus R5.4.1 — Shared Layer
Configuration, atomic file IO, notifications — used by daemon, dashboard, dry run.
"""
import datetime
import json
import logging
import os
import tempfile

import pytz
import requests
import telebot
from dotenv import load_dotenv

load_dotenv()

# ======================== Paths ========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AETHER_VERSION = "R5.4.1"
AETHER_TAGLINE = "IB Paper + Alpaca Data-Hardened Dry Run R5.4.1"
STATE_DIR = os.path.join(BASE_DIR, "state")
DRYRUN_STATE_DIR = os.path.join(BASE_DIR, "dryrun_state")
DRYRUN_SIGNALS_PATH = os.path.join(DRYRUN_STATE_DIR, "signals.json")
CMD_DIR = os.path.join(BASE_DIR, "commands")
os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(DRYRUN_STATE_DIR, exist_ok=True)
os.makedirs(CMD_DIR, exist_ok=True)

# ======================== Configuration ========================
IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "7497"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
PAPER_PORT = 7497
LIVE_PORT = 7496

PUSHOVER_USER = os.getenv("PUSHOVER_USER", "")
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# telegram | pushover | both (default: both; use telegram if Pushover not configured)
NOTIFY_CHANNEL = os.getenv("NOTIFY_CHANNEL", "both").lower()

MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
CAPITAL_PER_TRADE = float(os.getenv("CAPITAL_PER_TRADE", "1000.0"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.2"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.5"))
TRADING_START = os.getenv("TRADING_START", "10:00")
TRADING_END = os.getenv("TRADING_END", "15:00")
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

# Schedule (EST)
SCAN_PRE_MARKET = os.getenv("SCAN_PRE_MARKET", "09:00")
SCAN_POST_MARKET = os.getenv("SCAN_POST_MARKET", "16:30")
SCAN_REMINDER_MIN = int(os.getenv("SCAN_REMINDER_MIN", "5"))
MONITOR_INTERVAL_SEC = int(os.getenv("MONITOR_INTERVAL_SEC", "60"))
BUY_CHECK_INTERVAL_SEC = int(os.getenv("BUY_CHECK_INTERVAL_SEC", "120"))

# IB scan source: dryrun = aether_dryrun.py BFS (default); ib = legacy IB universe scan
IB_SCAN_SOURCE = os.getenv("IB_SCAN_SOURCE", "dryrun").lower().strip()

# Dry Run (Alpaca/Stooq/yfinance scanner — feeds IB buy logic when IB_SCAN_SOURCE=dryrun)
DRYRUN_SCAN_MODE = os.getenv("DRYRUN_SCAN_MODE", os.getenv("SCAN_MODE", "sp500")).lower().strip()
DRYRUN_POOL_DEFAULT = "MU,MRVL,AMD,HOOD,DELL,APA,OXY,IONQ,NVDA,TSLA,PLTR,COIN"
DRYRUN_POOL_SYMBOLS = [
    s.strip().upper()
    for s in os.getenv("POOL_SYMBOLS", DRYRUN_POOL_DEFAULT).split(",")
    if s.strip()
]

EST = pytz.timezone("US/Eastern")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("AetherNexus")


# ======================== Atomic file IO ========================
def atomic_write_json(filepath: str, data) -> None:
    """Write temp file then os.replace to avoid half-written reads."""
    tmp_path = None
    try:
        dir_name = os.path.dirname(filepath)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=dir_name, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            tmp_path = f.name
        os.replace(tmp_path, filepath)
    except Exception as e:
        logger.error("Atomic write failed %s: %s", filepath, e)
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def safe_read_json(filepath: str, default=None):
    """Safe JSON read; returns default if missing or corrupt."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default if default is not None else {}


def dryrun_row_to_ib_candidate(row: dict) -> dict:
    """Map Dry Run candidate dict → IB daemon / dashboard candidate row."""
    bid = row.get("bid") or 0
    ask = row.get("ask") or 0
    option_price = row.get("option_price")
    if not option_price or option_price <= 0:
        option_price = (bid + ask) / 2 if bid > 0 and ask > 0 else row.get("last_price") or 0
    return {
        "symbol": row.get("symbol", ""),
        "name": row.get("name", ""),
        "sector": row.get("sector", ""),
        "underlying_price": row.get("underlying_price"),
        "expiry": row.get("expiry", ""),
        "strike": row.get("strike"),
        "option_price": round(float(option_price), 4) if option_price else 0,
        "bid": bid,
        "ask": ask,
        "spread_pct": row.get("spread_pct"),
        "delta": row.get("delta"),
        "gamma": row.get("gamma"),
        "theta": row.get("theta"),
        "theta_ratio": row.get("theta_ratio"),
        "iv": row.get("iv"),
        "volume": row.get("volume"),
        "premium_dollars": row.get("premium_dollars"),
        "score": row.get("score"),
        "source": "dryrun",
        "scan_mode": row.get("scan_mode"),
        "price_source": row.get("price_source"),
    }


def export_dryrun_candidates_to_ib(candidates: list, scan_time: str, scan_mode: str) -> None:
    """Write latest Dry Run picks to state/candidates.json for IB daemon + dashboard."""
    rows = []
    for c in candidates:
        mapped = dryrun_row_to_ib_candidate(c)
        mapped["scan_mode"] = scan_mode
        rows.append(mapped)
    payload = {
        "rows": rows,
        "symbols": [r["symbol"] for r in rows],
        "scan_timestamp": scan_time,
        "source": "dryrun_bfs",
        "scan_mode": scan_mode,
    }
    atomic_write_json(os.path.join(STATE_DIR, "candidates.json"), payload)


def load_latest_dryrun_scan() -> dict:
    signals = safe_read_json(DRYRUN_SIGNALS_PATH, [])
    return signals[-1] if isinstance(signals, list) and signals else {}


# ======================== Command IO ========================
def send_command(cmd_name: str, payload: dict = None) -> None:
    """Dashboard writes a command file for the daemon."""
    filepath = os.path.join(CMD_DIR, f"{cmd_name}.cmd")
    data = {"cmd": cmd_name, "time": datetime.datetime.now(EST).isoformat()}
    if payload:
        data.update(payload)
    atomic_write_json(filepath, data)


def poll_commands() -> list:
    """Daemon reads and deletes all pending command files."""
    commands = []
    try:
        for name in os.listdir(CMD_DIR):
            if not name.endswith(".cmd"):
                continue
            filepath = os.path.join(CMD_DIR, name)
            data = safe_read_json(filepath)
            if data:
                commands.append(data)
            try:
                os.unlink(filepath)
            except OSError:
                pass
    except Exception as e:
        logger.error("Command poll failed: %s", e)
    return commands


# ======================== Notifications ========================
def _pushover_configured() -> bool:
    return bool(
        PUSHOVER_USER
        and PUSHOVER_TOKEN
        and PUSHOVER_USER not in ("your-user-key", "")
        and PUSHOVER_TOKEN not in ("your-app-token", "")
    )


def _telegram_configured() -> bool:
    return bool(
        TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
        and TELEGRAM_BOT_TOKEN not in ("your-bot-token", "")
        and TELEGRAM_CHAT_ID not in ("your-chat-id", "")
    )


def send_notification(message: str, priority: str = "normal") -> None:
    use_pushover = NOTIFY_CHANNEL in ("both", "pushover") and _pushover_configured()
    use_telegram = NOTIFY_CHANNEL in ("both", "telegram") and _telegram_configured()

    if priority == "critical":
        if use_pushover and _pushover(message, critical=True):
            return
        if use_telegram:
            prefix = "[CRITICAL] " if use_pushover else ""
            if _telegram(prefix + message):
                return
        logger.error("CRITICAL notification failed on all channels: %s", message[:120])
        return

    if use_pushover and _pushover(message):
        return
    if use_telegram:
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


def _telegram(message: str) -> bool:
    if not _telegram_configured():
        return False
    try:
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
        bot.send_message(TELEGRAM_CHAT_ID, message[:4096])
        return True
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False
