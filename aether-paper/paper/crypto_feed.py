"""Crypto 行情源 —— 对美国 IP 友好的公开接口,不需 key、不需 VPN。
   合规原则:只连允许美国访问的交易所公开行情(Coinbase / Kraken / CoinGecko)。
   绝不连被美国 IP 屏蔽的交易所(如 Bybit),绝不用 VPN 绕地域限制。
   纯行情读取,无下单、无密钥、无账户 —— 撮合与账户全在本地 paper 层。"""
from __future__ import annotations
import json
import logging
import ssl
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

try:
    import certifi
except ImportError:
    certifi = None  # type: ignore

# 合规白名单:这些交易所公开行情允许美国 IP
COINBASE = "https://api.exchange.coinbase.com"   # 美国合规,行情公开
KRAKEN = "https://api.kraken.com/0/public"      # 美国合规

# 屏蔽名单:美国 IP 被挡,禁止连(避免误配 + 提醒不要 VPN 绕)
BLOCKED_US = {"bybit.com", "binance.com"}          # 需 VPN 才能连 = 不合规,不碰

# 统一 symbol → 各所原生 id
_KRAKEN_PAIR = {
    "BTC-USD": "XBTUSD",
    "ETH-USD": "ETHUSD",
    "SOL-USD": "SOLUSD",
}


def _ssl_ctx() -> ssl.SSLContext:
    if certifi:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def _get(url: str, timeout: int = 10) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": "aether-paper/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            return json.load(r)
    except Exception as e:
        # M8: structured logging instead of print — crypto marks silently missing
        # previously left stops unable to fire on entry_price fallback.
        logger.warning("crypto_feed _get failed %s: %s: %s", url.split("/")[2], e.__class__.__name__, e)
        return None


def _assert_compliant(url: str) -> None:
    for blocked in BLOCKED_US:
        if blocked in url:
            raise RuntimeError(f"COMPLIANCE: {blocked} 对美国IP屏蔽,禁止连接(勿用VPN绕)")


def spot_price_coinbase(symbol: str = "BTC-USD") -> float | None:
    """Coinbase 现价。symbol 如 BTC-USD / ETH-USD / SOL-USD。"""
    url = f"{COINBASE}/products/{symbol}/ticker"
    _assert_compliant(url)
    d = _get(url)
    return round(float(d["price"]), 2) if d and "price" in d else None


def spot_price_kraken(symbol: str = "BTC-USD") -> float | None:
    """Kraken 现价。symbol 用统一 BTC-USD 格式。"""
    pair = _KRAKEN_PAIR.get(symbol)
    if not pair:
        return None
    url = f"{KRAKEN}/Ticker?pair={pair}"
    _assert_compliant(url)
    d = _get(url)
    if not d or d.get("error"):
        return None
    result = d.get("result") or {}
    if not result:
        return None
    row = next(iter(result.values()))
    # c = [last, lot volume]
    last = row.get("c", [None])[0]
    return round(float(last), 2) if last else None


def spot_price(symbol: str = "BTC-USD", *, prefer: str = "coinbase") -> float | None:
    """默认 Coinbase,失败则 Kraken fallback。"""
    order = ("coinbase", "kraken") if prefer == "coinbase" else ("kraken", "coinbase")
    for src in order:
        p = spot_price_coinbase(symbol) if src == "coinbase" else spot_price_kraken(symbol)
        if p is not None:
            return p
    return None


def marks(symbols: list[str], *, prefer: str = "coinbase") -> dict[str, float]:
    """批量取现价 → {symbol: price}。喂给 paper 引擎的 marks 参数。"""
    out: dict[str, float] = {}
    for s in symbols:
        p = spot_price(s, prefer=prefer)
        if p is not None:
            out[s] = p
        time.sleep(0.15)   # 温和,不打爆公开接口
    return out


def daily_candles(symbol: str = "BTC-USD", days: int = 30) -> list[dict] | None:
    """Coinbase 日线,给策略算信号用。granularity 86400 = 1天。"""
    url = f"{COINBASE}/products/{symbol}/candles?granularity=86400"
    _assert_compliant(url)
    d = _get(url)
    if not isinstance(d, list):
        return None
    # Coinbase candle: [time, low, high, open, close, volume]
    rows = [{"ts": c[0], "low": c[1], "high": c[2], "open": c[3],
             "close": c[4], "volume": c[5]} for c in d[:days]]
    return sorted(rows, key=lambda x: x["ts"])
