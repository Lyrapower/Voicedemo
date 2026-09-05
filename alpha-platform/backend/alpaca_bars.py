"""Alpaca stock bars 单一缝 —— 防陈旧K线(2026-08-07 事故锁)。

铁则(违反 = 再出现 July/开盘旧价当最新):
  1) 每次 /v2/stocks/bars 必须 sort=desc
  2) 有 limit 时必须带 start(或确认 desc 取最新)
  3) 多票批量后缺票必须逐票补
  4) 调用方若要时间正序数组,对本模块返回值 reverse,勿改 API sort

本模块供 worker / factor_truth / 静态门禁共用。
"""
from __future__ import annotations

from typing import Any

# 静态门禁扫这些文件;新增 bars 调用必须进名单并带 sort=desc
BARS_SOURCE_FILES = (
    "worker.py",
    "factor_truth.py",
    "alpaca_bars.py",
    "rvol_ic_study.py",
)

REQUIRED_BARS_PARAMS = ("sort",)  # 值必须为 desc


def bars_params(
    *,
    symbols: str,
    timeframe: str,
    limit: int,
    feed: str = "iex",
    start: str | None = None,
    end: str | None = None,
    adjustment: str = "raw",
    page_token: str | None = None,
) -> dict[str, Any]:
    """构造合法 bars query。强制 sort=desc。"""
    p: dict[str, Any] = {
        "symbols": symbols,
        "timeframe": timeframe,
        "limit": int(limit),
        "feed": feed,
        "sort": "desc",
        "adjustment": adjustment,
    }
    if start:
        p["start"] = start
    if end:
        p["end"] = end
    if page_token:
        p["page_token"] = page_token
    return p


def assert_bars_params_safe(params: dict[str, Any]) -> None:
    if str(params.get("sort") or "").lower() != "desc":
        raise ValueError("alpaca bars 禁止无 sort=desc(会吃到最旧K线)")
