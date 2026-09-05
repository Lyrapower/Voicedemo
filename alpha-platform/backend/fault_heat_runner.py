"""fault_heat_runner.py — 断层热力编排器 (ALPHA_FACTORY_GLM V1.2)。

worker 每轮(5min)调 tick(c, symbols)。内部按 ET 时闸分发:
- 05:45–05:50  fault-line 定版(每日一次):用 T−1 EOD surface 算 F1/F2/F4,落盘
- 05:50/06:05/06:20  盘前预热扫描(gap→F3 预置 + 贴断层→开盘即临断层)
- 06:35–13:00  盘中 H 计算:每标的每断层位算 H,cross 判定,推 Bark
- F4 每 30min 刷一次(状态型断层,位可变),状态变化推 iv_inversion

G 分量 60 日分位:读 data/faultlines/ 过去 60 日文件。
V 分量 vol_x20:近 5min 1min 量 / (20 日均日量/78) 代理(FMP 日线探活)。
"""
from __future__ import annotations
import os, sqlite3, datetime, logging, statistics, json
from typing import Any
from pathlib import Path

import fault_lines
import heat_h
import heat_anomaly_bark
import premarket_scan
import theta_options

log = logging.getLogger(__name__)
_ET = datetime.timezone(datetime.timedelta(hours=-4))  # EDT
FAULTLINE_DIR = Path(os.getenv("FAULTLINE_DIR", str(Path(__file__).resolve().parent.parent / "data" / "faultlines")))
F4_REFRESH_S = int(os.getenv("F4_REFRESH_M", "30")) * 60
SESSION_START_MIN = 6 * 60 + 35   # 06:35 ET
SESSION_END_MIN = 13 * 60         # 13:00 ET
FIX_START_MIN = 5 * 60 + 45       # 05:45 ET
FIX_END_MIN = 5 * 60 + 50         # 05:50 ET
HISTORY_DAYS = 60

_state: dict[str, Any] = {
    "last_fix_date": None,
    "last_premarket_slot": None,
    "last_f4_refresh_ts": 0.0,
    "prev_f4_state": {},  # sym -> f4_state
}


def _now_et() -> datetime.datetime:
    return datetime.datetime.now(_ET)


def _spot(c: sqlite3.Connection, sym: str) -> float | None:
    row = c.execute("SELECT c FROM bars WHERE symbol=? ORDER BY ts DESC LIMIT 1", (sym,)).fetchone()
    return float(row[0]) if row and row[0] else None


def _recent_closes(c: sqlite3.Connection, sym: str, n: int) -> list[float]:
    rows = c.execute("SELECT c FROM bars WHERE symbol=? ORDER BY ts DESC LIMIT ?", (sym, n)).fetchall()
    return [float(r[0]) for r in rows if r[0]][::-1]


def _recent_volumes(c: sqlite3.Connection, sym: str, n: int) -> list[float]:
    rows = c.execute("SELECT v FROM bars WHERE symbol=? ORDER BY ts DESC LIMIT ?", (sym, n)).fetchall()
    return [float(r[0]) for r in rows if r[0] is not None][::-1]


def _avg_daily_vol(c: sqlite3.Connection, sym: str, days: int = 20) -> float | None:
    """20 日均日量;只用综合量行(v2.5:排除 alpaca_iex 备份 bar)。"""
    try:
        rows = c.execute(
            "SELECT v FROM daily_bars WHERE symbol=? AND (src IS NULL OR src<>?) ORDER BY ts DESC LIMIT ?",
            (sym, "alpaca_iex", days),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = c.execute(
            "SELECT v FROM daily_bars WHERE symbol=? ORDER BY ts DESC LIMIT ?", (sym, days)
        ).fetchall()
    vals = [float(r[0]) for r in rows if r[0]]
    return statistics.mean(vals) if vals else None


def _ret_15m(c: sqlite3.Connection, sym: str) -> float:
    closes = _recent_closes(c, sym, 16)
    if len(closes) < 16 or not closes[-16]:
        return 0.0
    return (closes[-1] - closes[-16]) / closes[-16]


def _vol_x20(c: sqlite3.Connection, sym: str) -> float | None:
    """vol_x20 代理:近 5min 1min 量之和 / (20 日均日量/78)。"""
    vols = _recent_volumes(c, sym, 5)
    if not vols:
        return None
    recent_5 = sum(vols[-5:])
    avg_d = _avg_daily_vol(c, sym, 20)
    if not avg_d or avg_d <= 0:
        return None
    avg_5min = avg_d / 78.0  # 6.5h session = 78 个 5min 桶
    return recent_5 / avg_5min if avg_5min > 0 else None


def _crossed(c: sqlite3.Connection, sym: str, level: float | None) -> bool:
    """5min close 穿断层位:用最近两个 1min close 代理(prev, cur)。"""
    if level is None:
        return False
    closes = _recent_closes(c, sym, 2)
    if len(closes) < 2:
        return False
    prev, cur = closes[-2], closes[-1]
    return (prev < level <= cur) or (prev > level >= cur)


def _g_percentile(sym: str, fault_type: str, *, today_date: str, history_dir: Path | None = None) -> float | None:
    """从过去 60 日 faultlines 文件提取指标,算当日值的百分位。返回 [0,1] 或 None。"""
    d = history_dir or FAULTLINE_DIR
    vals: list[float] = []
    today = datetime.date.fromisoformat(today_date)
    for i in range(1, HISTORY_DAYS + 1):
        d_past = today - datetime.timedelta(days=i)
        fp = d / f"{d_past.isoformat()}.json"
        if not fp.exists():
            continue
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        block = next((s for s in payload.get("symbols", []) if s.get("symbol") == sym), None)
        if not block:
            continue
        faults = block.get("faults") or {}
        if fault_type == "F1_gamma_flip":
            f1 = faults.get("F1_gamma_flip") or {}
            slope = (f1.get("gex_slope") or {}).get("abs_avg")
            if slope is not None:
                vals.append(float(slope))
        elif fault_type == "F2_oi_wall":
            f2 = faults.get("F2_oi_walls") or {}
            for side in ("call", "put"):
                for w in f2.get(side) or []:
                    if w.get("oi"):
                        vals.append(float(w["oi"]))
    if len(vals) < 5:
        return None  # 历史不足,heat_h 回退中位
    fp_today = d / f"{today_date}.json"
    cur_val = None
    if fp_today.exists():
        try:
            payload = json.loads(fp_today.read_text(encoding="utf-8"))
            block = next((s for s in payload.get("symbols", []) if s.get("symbol") == sym), None)
            if block:
                faults = block.get("faults") or {}
                if fault_type == "F1_gamma_flip":
                    f1 = faults.get("F1_gamma_flip") or {}
                    cur_val = (f1.get("gex_slope") or {}).get("abs_avg")
                elif fault_type == "F2_oi_wall":
                    f2 = faults.get("F2_oi_walls") or {}
                    walls = [w.get("oi") for side in ("call", "put") for w in (f2.get(side) or []) if w.get("oi")]
                    cur_val = max(walls) if walls else None
        except Exception:
            pass
    if cur_val is None:
        return None
    rank = sum(1 for v in vals if v <= cur_val)
    return rank / len(vals)


def _build_and_persist_faultlines(date: str, symbols: list[str], c: sqlite3.Connection,
                                  out_dir: Path | None = None) -> int:
    """05:45 定版:为每个有 spot 的标的拉 T−1 EOD surface,算 F1/F2/F4,落盘。"""
    today = datetime.date.fromisoformat(date)
    t_minus_1 = today - datetime.timedelta(days=1)
    while t_minus_1.weekday() >= 5:
        t_minus_1 -= datetime.timedelta(days=1)
    theta_date = t_minus_1.isoformat()
    blocks: list[dict[str, Any]] = []
    for sym in symbols:
        spot = _spot(c, sym)
        if spot is None or spot <= 0:
            continue
        try:
            surf = theta_options.fetch_option_surface(sym, theta_date, spot)
        except Exception as exc:
            log.warning("faultline定版 theta %s %s: %s", sym, theta_date, exc)
            surf = None
        block = fault_lines.build_fault_lines(sym, date, spot, surface=surf)
        blocks.append(block)
    if not blocks:
        log.warning("faultline定版 %s: 无可用标的(无 spot 或 theta 全不可达)", date)
        return 0
    fp = fault_lines.persist_fault_lines(date, blocks, out_dir=out_dir)
    log.info("faultline定版 %s: %d symbols -> %s (theta_date=%s)", date, len(blocks), fp.name, theta_date)
    return len(blocks)


def _compute_and_push_h(date: str, symbols: list[str], c: sqlite3.Connection,
                         out_dir: Path | None = None) -> int:
    """盘中 H 计算:每标的每价位型断层算 H + cross,推 Bark。返回推送条数。"""
    fl = fault_lines.load_fault_lines(date, out_dir=out_dir)
    if not fl:
        return 0
    sym_blocks = {s["symbol"]: s for s in (fl.get("symbols") or []) if s.get("available")}
    pushed = 0
    now_ts = int(datetime.datetime.now(_ET).timestamp())
    for sym in symbols:
        block = sym_blocks.get(sym)
        if not block:
            continue
        price = _spot(c, sym)
        if price is None or price <= 0:
            continue
        faults = block.get("faults") or {}
        f4 = faults.get("F4_iv_inversion")
        f4_inverted = bool(f4 and f4.get("inverted"))
        ret_15m = _ret_15m(c, sym)
        vol_x20 = _vol_x20(c, sym)
        # F1 gamma flip
        f1 = faults.get("F1_gamma_flip")
        if f1 and f1.get("level") is not None:
            g_pct = _g_percentile(sym, "F1_gamma_flip", today_date=date, history_dir=out_dir)
            heat = heat_h.compute_heat(sym, "F1_gamma_flip", float(f1["level"]),
                                        price=price, spot=price, ret_15m=ret_15m, vol_x20=vol_x20,
                                        g_percentile=g_pct, f4_inverted=f4_inverted,
                                        crossed=_crossed(c, sym, f1["level"]))
            r = heat_anomaly_bark.push_heat(heat, data_asof_ts=now_ts, conn=c)
            if "已推送" in r:
                pushed += 1
        # F2 OI walls
        f2 = faults.get("F2_oi_walls") or {}
        g_pct2 = _g_percentile(sym, "F2_oi_wall", today_date=date, history_dir=out_dir)
        for side in ("call", "put"):
            for w in f2.get(side) or []:
                lvl = w.get("K")
                if lvl is None:
                    continue
                heat = heat_h.compute_heat(sym, "F2_oi_wall", float(lvl),
                                            price=price, spot=price, ret_15m=ret_15m, vol_x20=vol_x20,
                                            g_percentile=g_pct2, f4_inverted=f4_inverted,
                                            crossed=_crossed(c, sym, lvl))
                r = heat_anomaly_bark.push_heat(heat, data_asof_ts=now_ts, conn=c)
                if "已推送" in r:
                    pushed += 1
        # F3 gap edge
        f3 = faults.get("F3_gap_edge")
        if f3:
            for edge_key in ("upper", "lower"):
                lvl = f3.get(edge_key)
                if lvl is None:
                    continue
                heat = heat_h.compute_heat(sym, "F3_gap_edge", float(lvl),
                                            price=price, spot=price, ret_15m=ret_15m, vol_x20=vol_x20,
                                            g_percentile=None, f4_inverted=f4_inverted,
                                            crossed=_crossed(c, sym, lvl))
                r = heat_anomaly_bark.push_heat(heat, data_asof_ts=now_ts, conn=c)
                if "已推送" in r:
                    pushed += 1
    return pushed


def _refresh_f4_intraday(date: str, symbols: list[str], c: sqlite3.Connection,
                          out_dir: Path | None = None) -> int:
    """F4 每 30min 刷:重拉 surface,更新 F4 状态,状态变化推 iv_inversion。

    NOTE: 当前用 fetch_option_surface(今日) 返回最新可用 EOD(常为昨日)。
    盘中真实 IV 变化需 Theta intraday 端点(Phase 0 探活),结构已就位,接入即用。
    """
    today = datetime.date.fromisoformat(date)
    theta_date = today.isoformat()
    pushed = 0
    now_ts = int(datetime.datetime.now(_ET).timestamp())
    for sym in symbols:
        spot = _spot(c, sym)
        if spot is None:
            continue
        try:
            surf = theta_options.fetch_option_surface(sym, theta_date, spot)
        except Exception:
            surf = None
        if not surf:
            continue
        f4_state = fault_lines.compute_f4_iv_inversion(surf)
        prev = _state["prev_f4_state"].get(sym)
        r = heat_anomaly_bark.push_iv_inversion(sym, f4_state, prev_f4_state=prev,
                                                data_asof_ts=now_ts, conn=c)
        if "已推送" in r:
            pushed += 1
        fault_lines.update_f4_intraday(date, sym, f4_state, out_dir=out_dir)
        _state["prev_f4_state"][sym] = f4_state
    return pushed


def tick(c: sqlite3.Connection, symbols: list[str], *, now_et: datetime.datetime | None = None,
         out_dir: Path | None = None) -> dict:
    """worker 每轮调。按 ET 时闸分发定版/盘前扫描/盘中 H/F4 刷新。返回本轮动作摘要。"""
    now = now_et or _now_et()
    date = now.date().isoformat()
    cur_min = now.hour * 60 + now.minute
    actions: list[str] = []

    # 1) 05:45 定版(每日一次,允许补跑:文件不存在则建)
    fp = (out_dir or FAULTLINE_DIR) / f"{date}.json"
    need_fix = (FIX_START_MIN <= cur_min < FIX_END_MIN) and (_state["last_fix_date"] != date)
    if not need_fix and (cur_min >= FIX_START_MIN) and (_state["last_fix_date"] != date) and not fp.exists():
        need_fix = True  # 补跑:worker 起得晚或重启后
    if need_fix:
        try:
            n = _build_and_persist_faultlines(date, symbols, c, out_dir=out_dir)
            _state["last_fix_date"] = date
            actions.append(f"fix:{n}")
        except Exception as exc:
            log.exception("faultline定版 failed: %s", exc)
            actions.append(f"fix_err")

    # 2) 盘前预热扫描(05:50/06:05/06:20)
    slot = premarket_scan.should_run_premarket(now, _state["last_premarket_slot"])
    if slot is not None:
        try:
            res = premarket_scan.scan_premarket(date, symbols, conn=c, out_dir=out_dir)
            _state["last_premarket_slot"] = slot
            actions.append(f"pre:{res['scanned']}/f3{res['f3_preset']}/near{res['near_fault_pushed']}")
        except Exception:
            log.exception("premarket scan failed")
            actions.append("pre_err")

    # 3) 盘中 H 计算(06:35–13:00)
    if SESSION_START_MIN <= cur_min < SESSION_END_MIN:
        try:
            pushed = _compute_and_push_h(date, symbols, c, out_dir=out_dir)
            if pushed:
                actions.append(f"h_push:{pushed}")
        except Exception:
            log.exception("H compute failed")
            actions.append("h_err")
        # F4 30min 刷
        now_s = now.timestamp()
        if now_s - _state["last_f4_refresh_ts"] >= F4_REFRESH_S:
            try:
                fp4 = _refresh_f4_intraday(date, symbols, c, out_dir=out_dir)
                _state["last_f4_refresh_ts"] = now_s
                if fp4:
                    actions.append(f"f4_push:{fp4}")
            except Exception:
                log.exception("F4 refresh failed")
                actions.append("f4_err")

    return {"date": date, "et_min": cur_min, "actions": actions}


def reset_state() -> None:
    """测试用:清空编排器内存状态。"""
    _state.update({"last_fix_date": None, "last_premarket_slot": None,
                   "last_f4_refresh_ts": 0.0, "prev_f4_state": {}})
