"""heat_anomaly_bark.py — 断层热力 H 值 Bark 推送 (ALPHA_FACTORY_GLM V1.2)。

替换旧 ret_5m 异常检测。基于 heat_h.compute_heat 的 H 值:
- H ≥ 阈值(默认 70) → 推送,30min 冷却 per(symbol, fault_type, fault_level)
- cross 事件(5min close 穿断层位 + V≥1.5)→ 单独冷却推送
- F4 IV 期限倒挂:状态变化(发生/加深)单独推 fault_type=iv_inversion
- stale 守卫:push_ts − data_asof_ts > 5min → 禁推(过时数据不推)
- payload 固定字段,零 LLM,标明数据源

冷却持久跨重启:db.heat_push_log 表(无表则回退内存 dict)。
"""
from __future__ import annotations
import os, time, sqlite3, datetime, urllib.request, urllib.parse, json, logging
from typing import Any

log = logging.getLogger(__name__)
HEAT_H_THRESHOLD = float(os.getenv("HEAT_H_THRESHOLD", "70"))
HEAT_COOLDOWN_S = int(os.getenv("HEAT_COOLDOWN_M", "30")) * 60
CROSS_COOLDOWN_S = int(os.getenv("HEAT_CROSS_COOLDOWN_M", "60")) * 60
F4_COOLDOWN_S = int(os.getenv("HEAT_F4_COOLDOWN_M", "30")) * 60
STALE_S = int(os.getenv("HEAT_STALE_S", "300"))  # 5min

_mem_log: dict[tuple, tuple[float, float]] = {}  # key -> (last_push_ts, last_value)


def _bark_url() -> str:
    env = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "grid", "pipeline_doctor.env"))
    if os.path.isfile(env):
        for line in open(env, encoding="utf-8"):
            s = line.strip()
            if s.startswith("DOCTOR_BARK_URL="):
                return s.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
    return os.getenv("DOCTOR_BARK_URL", "").strip().rstrip("/")


def send_bark(title: str, body: str, *, group: str = "heat-faultline") -> str:
    bark = _bark_url()
    if not bark:
        return "未配置 DOCTOR_BARK_URL"
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    payload = {"title": title, "body": body, "group": group}
    try:
        req = urllib.request.Request(bark, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urllib.request.urlopen(req, timeout=12, context=ctx) as r:
            return "已推送" if r.status == 200 else f"HTTP {r.status}"
    except Exception:
        try:
            url = f"{bark}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
            with urllib.request.urlopen(url, timeout=12, context=ctx) as r:
                return "已推送(GET)" if r.status == 200 else f"GET {r.status}"
        except Exception as e:
            return f"失败:{e}"


def _symbol_source(c: sqlite3.Connection, sym: str) -> str:
    srcs = []
    try:
        row = c.execute("SELECT source, last_on FROM heat_nominations WHERE symbol=?", (sym,)).fetchone()
    except Exception:
        row = None
    if row:
        if row[0] == "scan":
            age_tag = ""
            try:
                last = datetime.date.fromisoformat(row[1])
                age = (datetime.date.today() - last).days
                age_tag = f" {age}d" + (" ⚠过期" if age > 3 else "")
            except Exception:
                pass
            srcs.append(f"bfs scan({row[1]}{age_tag})")
        elif row[0] == "movers":
            srcs.append("sp500 当日")
    try:
        import db
        if sym in getattr(db, "BASE_WATCHLIST", set()):
            srcs.append("env watchlist")
    except Exception:
        pass
    def _has(table):
        try:
            return c.execute(f"SELECT 1 FROM {table} WHERE symbol=? LIMIT 1", (sym,)).fetchone()
        except Exception:
            return None
    if _has("bars"):
        srcs.append("alpaca 1min")
    if _has("daily_bars"):
        srcs.append("fmp daily")
    try:
        if c.execute("SELECT 1 FROM factors WHERE symbol=? AND name='net_gex' LIMIT 1", (sym,)).fetchone():
            srcs.append("theta options")
    except Exception:
        pass
    return " · ".join(srcs) if srcs else "未知"


def _ensure_log_table(c: sqlite3.Connection) -> bool:
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS heat_push_log (
            symbol TEXT, fault_type TEXT, fault_level REAL, push_kind TEXT,
            last_push_ts REAL, last_value REAL,
            PRIMARY KEY(symbol, fault_type, fault_level, push_kind))""")
        return True
    except Exception:
        return False


def _log_get(c: sqlite3.Connection | None, key: tuple) -> tuple[float, float] | None:
    if c is not None and _ensure_log_table(c):
        sym, ft, lvl, kind = key
        try:
            row = c.execute("SELECT last_push_ts, last_value FROM heat_push_log WHERE symbol=? AND fault_type=? AND fault_level=? AND push_kind=?",
                           (sym, ft, lvl, kind)).fetchone()
            return (float(row[0]), float(row[1])) if row else None
        except Exception:
            pass
    return _mem_log.get(key)


def _log_set(c: sqlite3.Connection | None, key: tuple, ts: float, value: float) -> None:
    if c is not None and _ensure_log_table(c):
        sym, ft, lvl, kind = key
        try:
            c.execute("""INSERT INTO heat_push_log(symbol,fault_type,fault_level,push_kind,last_push_ts,last_value)
                         VALUES(?,?,?,?,?,?) ON CONFLICT(symbol,fault_type,fault_level,push_kind)
                         DO UPDATE SET last_push_ts=excluded.last_push_ts, last_value=excluded.last_value""",
                      (sym, ft, lvl, kind, ts, value))
            c.commit()
            return
        except Exception:
            pass
    _mem_log[key] = (ts, value)


def _stale_check(data_asof_ts: float | None, now: float) -> tuple[bool, str]:
    if data_asof_ts is None:
        return True, "无 data_asof"
    age = now - data_asof_ts
    if age > STALE_S:
        return True, f"stale {int(age)}s>{STALE_S}s"
    if age < -30:  # 数据时间戳比推送时间还新(时钟错乱)
        return True, f"future {int(age)}s"
    return False, ""


def push_heat(heat: dict[str, Any], *, data_asof_ts: float | None, conn: sqlite3.Connection | None = None) -> str:
    """H≥阈值 或 cross 事件 → 推送。带 stale 守卫 + 冷却 + 去重(value 不变不推)。"""
    if not heat.get("hot") and not heat.get("cross_event"):
        return "未达阈值"
    now = time.time()
    stale, why = _stale_check(data_asof_ts, now)
    if stale:
        log.warning("heat push skipped: %s sym=%s", why, heat.get("symbol"))
        return f"跳过(stale:{why})"
    sym = heat["symbol"]
    ft = heat["fault_type"]
    lvl = heat.get("fault_level")
    lvl_key = round(lvl, 2) if lvl is not None else 0.0
    src = _symbol_source(conn, sym) if conn is not None else "未知"
    pushed = []
    # 1) H 热力推送
    if heat.get("hot"):
        key = (sym, ft, lvl_key, "heat")
        prev = _log_get(conn, key)
        if prev and now - prev[0] < HEAT_COOLDOWN_S and abs(prev[1] - heat["H"]) < 0.5:
            pass  # 冷却中且值未变
        else:
            title = f"断层热力 {sym}·{ft} H={heat['H']}"
            ts_str = datetime.datetime.fromtimestamp(data_asof_ts).strftime("%H:%M:%S")
            body = (f"{ft}@{lvl} | 价{heat.get('price','?')} | H={heat['H']} "
                   f"(D={heat['D']} M={heat['M']} G={heat['G']} V={heat['V']}) | "
                   f"vol_x20={heat.get('vol_x20')} | ret_15m={heat.get('ret_15m')} | "
                   f"{'IV倒挂加成 ' if heat.get('f4_inverted') else ''}"
                   f"{ts_str} | {src}")
            res = send_bark(title, body)
            _log_set(conn, key, now, heat["H"])
            pushed.append(f"heat:{res}")
    # 2) cross 事件推送(独立冷却)
    if heat.get("cross_event"):
        key = (sym, ft, lvl_key, "cross")
        prev = _log_get(conn, key)
        if prev and now - prev[0] < CROSS_COOLDOWN_S:
            pass
        else:
            title = f"断层穿透 {sym}·{ft} @ {lvl}"
            ts_str = datetime.datetime.fromtimestamp(data_asof_ts).strftime("%H:%M:%S")
            body = (f"5min close 穿 {ft}@{lvl} | H={heat['H']} | vol_x20={heat.get('vol_x20')}≥{os.getenv('HEAT_V_CONFIRM','1.5')} | "
                   f"{'IV倒挂 ' if heat.get('f4_inverted') else ''}{ts_str} | {src}")
            res = send_bark(title, body, group="heat-cross")
            _log_set(conn, key, now, heat["H"])
            pushed.append(f"cross:{res}")
    return " · ".join(pushed) if pushed else "冷却中(值未变)"


def push_iv_inversion(symbol: str, f4_state: dict[str, Any] | None, *,
                      prev_f4_state: dict[str, Any] | None,
                      data_asof_ts: float | None, conn: sqlite3.Connection | None = None) -> str:
    """F4 IV 期限倒挂:状态变化(发生/加深)单独推 fault_type=iv_inversion。

    发生: prev 无倒挂 → 当前倒挂。
    加深: prev 倒挂 且 ratio 上升 ≥ 0.03(可配)。
    """
    now = time.time()
    stale, why = _stale_check(data_asof_ts, now)
    if stale:
        return f"跳过(stale:{why})"
    if not f4_state or not f4_state.get("inverted"):
        return "未倒挂"
    prev_inv = bool(prev_f4_state and prev_f4_state.get("inverted"))
    prev_ratio = float(prev_f4_state.get("ratio") or 0) if prev_f4_state else 0.0
    cur_ratio = float(f4_state.get("ratio") or 0)
    deepen = float(os.getenv("F4_DEEPEN_RATIO", "0.03"))
    occurred = (not prev_inv) and f4_state.get("inverted")
    deepened = prev_inv and (cur_ratio - prev_ratio) >= deepen
    if not (occurred or deepened):
        return "无状态变化"
    key = (symbol, "F4_iv_inversion", 0.0, "iv_inversion")
    prev = _log_get(conn, key)
    if prev and now - prev[0] < F4_COOLDOWN_S:
        return "F4 冷却中"
    src = _symbol_source(conn, symbol) if conn is not None else "theta options"
    kind = "发生" if occurred else f"加深(+{round(cur_ratio - prev_ratio, 3)})"
    title = f"IV期限倒挂 {symbol}·{kind}"
    ts_str = datetime.datetime.fromtimestamp(data_asof_ts).strftime("%H:%M:%S")
    body = (f"近月IV={f4_state.get('near_iv')} 次月IV={f4_state.get('next_iv')} ratio={cur_ratio} | "
            f"近月{f4_state.get('near_exp')} 次月{f4_state.get('next_exp')} | {kind} | "
            f"{ts_str} | {src}")
    res = send_bark(title, body, group="heat-iv-inversion")
    _log_set(conn, key, now, cur_ratio)
    return f"iv_inversion:{res}"


def scan_and_push(*args, **kwargs) -> str:  # 旧入口兼容(已弃用,转调 push_heat)
    return "已弃用:改用 push_heat"
