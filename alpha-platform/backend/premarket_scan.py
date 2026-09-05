"""premarket_scan.py — 盘前预热扫描 (ALPHA_FACTORY_GLM V1.2)。

05:45 定版断层位之后,05:50–06:25 每 15 分钟扫几轮盘前价:
- gap 够大(≥1.5×ATR14)→ 提前定 F3 边界(merge_f3)
- 盘前价已贴断层位(proximity band 内)→ 开盘前推一条"开盘即临断层"

6:45 看晨报之前,手机上已经知道今天谁站在断层边上了。
"""
from __future__ import annotations
import os, sqlite3, datetime, logging
from typing import Any, Callable
from pathlib import Path

import fault_lines
import heat_anomaly_bark
import heat_h

log = logging.getLogger(__name__)
_ET = datetime.timezone(datetime.timedelta(hours=-4))  # EDT
PROXIMITY_BAND = float(os.getenv("HEAT_PROXIMITY_BAND", "0.015"))
PREMARKET_NEAR_FACTOR = float(os.getenv("PREMARKET_NEAR_FACTOR", "1.0"))  # 盘前贴断层判定 = proximity band × 此因子


def _atr14(c: sqlite3.Connection, sym: str) -> float | None:
    """14 日 ATR(真波幅均值),用 daily_bars。"""
    rows = c.execute(
        "SELECT h, l, c FROM daily_bars WHERE symbol=? ORDER BY ts DESC LIMIT 15", (sym,)
    ).fetchall()
    if len(rows) < 14:
        return None
    trs = []
    prev_close = None
    for h, l, cl in rows[::-1]:  # 升序
        if prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = cl
    if len(trs) < 14:
        return None
    return sum(trs[-14:]) / 14.0


def _prev_close(c: sqlite3.Connection, sym: str) -> float | None:
    row = c.execute(
        "SELECT c FROM daily_bars WHERE symbol=? ORDER BY ts DESC LIMIT 1", (sym,)
    ).fetchone()
    return float(row[0]) if row and row[0] else None


def _latest_price(c: sqlite3.Connection, sym: str) -> float | None:
    """盘前价代理:bars 表最新 1min close(若 Alpaca IEX 含盘前则为准,否则用最近收盘)。"""
    row = c.execute(
        "SELECT c FROM bars WHERE symbol=? ORDER BY ts DESC LIMIT 1", (sym,)
    ).fetchone()
    return float(row[0]) if row and row[0] else None


def _collect_fault_levels(sym_block: dict[str, Any]) -> list[tuple[str, float]]:
    """从 faultlines 单标的块提取所有价位型断层位 [(fault_type, level), ...]。"""
    out: list[tuple[str, float]] = []
    faults = sym_block.get("faults") or {}
    f1 = faults.get("F1_gamma_flip")
    if f1 and f1.get("level") is not None:
        out.append(("F1_gamma_flip", float(f1["level"])))
    f2 = faults.get("F2_oi_walls") or {}
    for side in ("call", "put"):
        for w in f2.get(side) or []:
            if w.get("K") is not None:
                out.append(("F2_oi_wall", float(w["K"])))
    f3 = faults.get("F3_gap_edge")
    if f3:
        if f3.get("upper") is not None:
            out.append(("F3_gap_edge", float(f3["upper"])))
        if f3.get("lower") is not None and f3.get("lower") != f3.get("upper"):
            out.append(("F3_gap_edge", float(f3["lower"])))
    return out


def scan_premarket(date: str, symbols: list[str], *, conn: sqlite3.Connection,
                   out_dir: Path | None = None,
                   price_provider: Callable[[sqlite3.Connection, str], float | None] | None = None) -> dict:
    """跑一轮盘前预热扫描。返回 {scanned, f3_preset, near_fault_pushed, errors}。

    price_provider 默认读 bars 表最新 close。可注入更准的盘前 quote 源。
    """
    fl = fault_lines.load_fault_lines(date, out_dir=out_dir)
    if not fl:
        return {"scanned": 0, "f3_preset": 0, "near_fault_pushed": 0, "errors": ["faultlines 未定版"]}
    sym_blocks = {s["symbol"]: s for s in (fl.get("symbols") or []) if s.get("available")}
    get_price = price_provider or _latest_price
    scanned = f3_preset = near_pushed = 0
    errors: list[str] = []
    near_band = PROXIMITY_BAND * PREMARKET_NEAR_FACTOR
    for sym in symbols:
        block = sym_blocks.get(sym)
        if not block:
            continue
        price = get_price(conn, sym)
        prev = _prev_close(conn, sym)
        atr = _atr14(conn, sym)
        if price is None or prev is None:
            continue
        scanned += 1
        # 1) gap 够大 → 提前定 F3
        gap = price - prev
        if atr and abs(gap) >= 1.5 * atr:
            f3 = fault_lines.compute_f3_gap_edge(price, prev, atr)
            if f3 and not (block.get("faults") or {}).get("F3_gap_edge"):
                fault_lines.merge_f3(date, sym, f3, out_dir=out_dir)
                f3_preset += 1
                log.info("premarket F3 preset %s gap=%s atr=%s", sym, round(gap, 2), round(atr, 2))
        # 2) 贴断层位 → 推"开盘即临断层"
        levels = _collect_fault_levels(block)
        for ft, lvl in levels:
            dist = abs(price - lvl) / price if price else 1.0
            if dist <= near_band:
                ts = int(datetime.datetime.now(_ET).timestamp())
                title = f"开盘即临断层 {sym}·{ft}"
                body = (f"盘前价 {price} 贴 {ft}@{lvl} (距 {round(dist*100,2)}% ≤ {round(near_band*100,2)}%) | "
                        f"prev_close={prev} | {date} | 结构参考,非信号")
                res = heat_anomaly_bark.send_bark(title, body, group="heat-premarket-near")
                near_pushed += 1
                log.info("premarket near-fault push %s %s @%s -> %s", sym, ft, lvl, res)
                break  # 同标的一轮只推一条
    return {"scanned": scanned, "f3_preset": f3_preset, "near_fault_pushed": near_pushed, "errors": errors}


# 盘前扫描时点(ET):05:50, 06:05, 06:20
PREMARKET_SLOTS_ET = [5 * 60 + 50, 6 * 60 + 5, 6 * 60 + 20]


def should_run_premarket(now_et: datetime.datetime, last_slot_ts: float | None) -> int | None:
    """返回应跑的 slot 分钟数(05:50=350,06:05=365,06:20=380),否则 None。

    判定:当前 ET 分钟数 ≥ 某 slot 且该 slot 未跑过(用 last_slot_ts 标记最后跑的 slot 分钟数)。
    """
    cur_min = now_et.hour * 60 + now_et.minute
    last_min = int(last_slot_ts) if last_slot_ts is not None else -1
    for slot in PREMARKET_SLOTS_ET:
        if cur_min >= slot and slot > last_min:
            return slot
    return None
