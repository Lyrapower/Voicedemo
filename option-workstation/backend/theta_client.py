"""theta_client.py —— 经本机 Theta Terminal HTTP 拉 EOD(零密钥;Terminal 已鉴权)。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# compose 内: http://theta-terminal:25503 ; 宿主机默认 localhost
DEFAULT_BASE = os.getenv("THETA_BASE", "http://127.0.0.1:25503").rstrip("/")


class ThetaError(RuntimeError):
    pass


def _get(path: str, params: dict[str, Any] | None = None, *, base: str | None = None) -> Any:
    b = (base or DEFAULT_BASE).rstrip("/")
    q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{b}{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise ThetaError(f"HTTP {e.code} {path}: {body}") from e
    except urllib.error.URLError as e:
        raise ThetaError(f"连不上 Theta Terminal ({b}): {e.reason}") from e
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ThetaError(f"非 JSON: {raw[:200]}") from e


def ping(base: str | None = None) -> dict[str, Any]:
    """探测 Terminal 是否在听 + 已鉴权。v3:用 /v3/stock/list/symbols(轻量、需鉴权)。

    v2/v3 的 /system/status 端点在 v3 Terminal 已 410/404,改用业务端点做存活+鉴权探测。
    """
    last: Exception | None = None
    for path in (
        "/v3/stock/list/symbols?format=json",
    ):
        try:
            data = _get(path, base=base)
            return {"ok": True, "path": path, "data": data}
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    return {"ok": False, "error": str(last or "unreachable")}


def stock_eod(root: str, yyyymmdd: int, *, base: str | None = None) -> dict[str, Any] | None:
    """标的 EOD;用于 spot。v3:用 symbol(非 root)+ format=json。"""
    date_iso = f"{yyyymmdd // 10000:04d}-{(yyyymmdd // 100) % 100:02d}-{yyyymmdd % 100:02d}"
    for path in ("/v3/stock/history/eod", "/v2/hist/stock/eod"):
        try:
            data = _get(
                path,
                {
                    "symbol": root,
                    "start_date": yyyymmdd,
                    "end_date": yyyymmdd,
                    "date": date_iso,
                    "format": "json",
                },
                base=base,
            )
            if data:
                return data if isinstance(data, dict) else {"response": data}
        except ThetaError:
            continue
    return None


def stock_eod_series(root: str, end_yyyymmdd: int, *, days: int = 45, base: str | None = None) -> list[float]:
    """Fetch a daily-close series ending at end_yyyymmdd (calendar range ~`days` back).

    O2: `build_snapshot` previously set `hist_tail = [spot]` (1 point), so
    `cleaning.features()` could never compute RV20 (needs ≥21) → VRP20 always null.
    Returns ascending list of closes (may be < 21 if the feed returns fewer).
    """
    import datetime as _dt

    end = _dt.date(end_yyyymmdd // 10000, (end_yyyymmdd // 100) % 100, end_yyyymmdd % 100)
    start = end - _dt.timedelta(days=days)
    start_ymd = int(start.strftime("%Y%m%d"))
    for path in ("/v3/stock/history/eod", "/v2/hist/stock/eod"):
        try:
            data = _get(
                path,
                {
                    "symbol": root,
                    "start_date": start_ymd,
                    "end_date": end_yyyymmdd,
                    "date": f"{start_ymd // 10000:04d}-{(start_ymd // 100) % 100:02d}-{start_ymd % 100:02d}",
                    "format": "json",
                },
                base=base,
            )
        except ThetaError:
            continue
        rows = []
        if isinstance(data, dict):
            rows = data.get("response") or data.get("data") or data.get("ticks") or []
        elif isinstance(data, list):
            rows = data
        closes: list[float] = []
        for r in rows or []:
            c = None
            if isinstance(r, dict):
                c = r.get("close")
            elif isinstance(r, (list, tuple)) and len(r) >= 6:
                c = r[5]
            if c is not None:
                try:
                    closes.append(float(c))
                except (TypeError, ValueError):
                    continue
        if closes:
            return closes
    return []


def bulk_option_eod(
    root: str,
    yyyymmdd: int,
    *,
    exp: int = 0,
    base: str | None = None,
) -> Any:
    """全链 EOD。exp=0 = 该 root 全部到期(须按日请求)。v3:用 symbol + format=json。"""
    # M: Terminal runs v3 on 25503 — try v3 first; v2 may 410 on a v3 Terminal.
    # Previously v2 was first and v3 was fallback, so v2 410 silently fell through.
    errors: list[str] = []
    for path in (
        "/v3/option/history/eod",
        "/v2/bulk_hist/option/eod",
    ):
        params = {
            "symbol": root,
            "expiration": "*" if exp == 0 else exp,
            "start_date": yyyymmdd,
            "end_date": yyyymmdd,
            "date": f"{yyyymmdd // 10000:04d}-{(yyyymmdd // 100) % 100:02d}-{yyyymmdd % 100:02d}",
            "format": "json",
        }
        try:
            return _get(path, params, base=base)
        except ThetaError as e:
            errors.append(f"{path}: {e}")
            continue
    raise ThetaError("bulk_option_eod 失败:\n" + "\n".join(errors))


def option_history_open_interest(
    root: str,
    yyyymmdd: int,
    *,
    base: str | None = None,
) -> Any:
    """v3 OI 端点(独立于 EOD 价格端点)。返回 {response:[{contract,data:[{open_interest,...}]}]}。

    v3 把 open_interest 拆成独立端点 /v3/option/history/open_interest;
    EOD 价格端点(/v3/option/history/eod)不再返回 OI 列。
    OI 由 OPRA 每日 ~06:30 ET 报告一次,代表前一交易日收盘的 OI。
    """
    date_iso = f"{yyyymmdd // 10000:04d}-{(yyyymmdd // 100) % 100:02d}-{yyyymmdd % 100:02d}"
    params = {
        "symbol": root,
        "expiration": "*",
        "date": date_iso,
        "format": "json",
    }
    return _get("/v3/option/history/open_interest", params, base=base)
