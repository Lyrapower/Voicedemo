#!/usr/bin/env python3
"""BFS Watchdog v1 — R5.4.1 BFS SP500 线的确定性运维哨兵。

================================================================================
CHANGELOG
--------------------------------------------------------------------------------
v1 (2026-07-24, Fable/守恒 · Grid 判词:底座本地 9B,检查为确定性代码,
    LLM 仅在异常时被调用写摘要,失败不阻断告警)
  四环检查(每交易日 09:55 / 15:45 ET 各跑一次,由 launchd 触发):
    C1 heartbeat  — dryrun_state/heartbeat.json 的 last_scan_ts 是否在本窗口内
    C2 store 入库 — aether_scan(label=BFS sp500, date=今日ET, window=AM/PM)是否到位
    C3 integrity  — payload.status=="ok" 且 universe_size 达标
                    (rows 为空 + status ok = 本轮无候选,合法,不告警)
    C4 telegram   — dryrun 日志尾部是否有本窗口的发送证据(路径未配则如实报 SKIPPED)
  绿:仅 emit aether_watchdog(status=ok)入 store,零打扰。
  红:emit alert + 走既有 TELEGRAM_* 发告警;9B 摘要尽力而为,10s 超时即降级为纯事实告警。
  哨兵自身出错:发一条 watchdog internal error,绝不静默死亡。
  依赖:纯 stdlib。凭证/端点全部复用既有 env(TELEGRAM_*、ALPACA_*、GRID_EVENTS),
  零新服务、零新 key(铁则)。
================================================================================
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

# ---------------- CONFIG(部署时由 Cursor 在 plist EnvironmentVariables 填绝对路径) ----------------
STORE_DB = os.getenv("WATCHDOG_STORE_DB", "")            # e.g. /Users/.../grid-sovereign-runtime/data/grid_store.db
HEARTBEAT_PATH = os.getenv("WATCHDOG_HEARTBEAT", "")     # e.g. /Users/.../aether_nexus/dryrun_state/heartbeat.json
DRYRUN_LOG = os.getenv("WATCHDOG_DRYRUN_LOG", "")        # dryrun 日志文件;留空则 C4 报 SKIPPED
TG_OK_MARKER = os.getenv("WATCHDOG_TG_OK_MARKER", "BFS sp500 Scan")   # 日志中发送成功的证据子串
LOCAL_LLM_URL = os.getenv("WATCHDOG_LLM_URL", "")        # 本地 9B 端点(OpenAI 兼容 /v1/chat/completions);留空禁用
LOCAL_LLM_MODEL = os.getenv("WATCHDOG_LLM_MODEL", "demo/aster")
GRID_EVENTS = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
STATE_PATH = os.getenv("WATCHDOG_STATE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchdog_state.json"))
UNIVERSE_MIN = int(os.getenv("WATCHDOG_UNIVERSE_MIN", "400"))
HEARTBEAT_GRACE_MIN = int(os.getenv("WATCHDOG_HB_GRACE_MIN", "45"))
LOG_TAIL_BYTES = 65536

ET = ZoneInfo("America/New_York")
SCAN_START = {"AM": (9, 40), "PM": (15, 30)}

logging.basicConfig(level=logging.INFO, format="%(asctime)s watchdog %(levelname)s %(message)s")
log = logging.getLogger("bfs_watchdog")


def _http_json(url: str, *, data: dict | None = None, headers: dict | None = None, timeout: int = 10):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if body else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def is_trading_day(d: dt.date) -> bool:
    """与 dryrun 同策略:周末必休;有 Alpaca key 则查 /v2/calendar,查不到默认开市。"""
    if d.weekday() >= 5:
        return False
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        return True
    try:
        key = d.isoformat()
        url = "https://paper-api.alpaca.markets/v2/calendar?" + urllib.parse.urlencode({"start": key, "end": key})
        data = _http_json(url, headers={"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}, timeout=5)
        return any(e.get("date") == key for e in (data if isinstance(data, list) else []))
    except Exception as exc:  # 日历不可达 → 与 dryrun 同,默认开市
        log.warning("calendar unreachable (%s) — assume open", exc)
        return True


def check_heartbeat(now_et: dt.datetime, window: str) -> tuple[str, str]:
    if not HEARTBEAT_PATH:
        return "SKIPPED", "WATCHDOG_HEARTBEAT 未配置"
    try:
        with open(HEARTBEAT_PATH, encoding="utf-8") as f:
            ts = dt.datetime.fromisoformat(json.load(f)["last_scan_ts"])
    except FileNotFoundError:
        return "FAIL", "heartbeat.json 不存在"
    except Exception as exc:
        return "FAIL", f"heartbeat 解析失败: {exc}"
    h, m = SCAN_START[window]
    scan_start = now_et.replace(hour=h, minute=m, second=0, microsecond=0)
    age_ok = scan_start - dt.timedelta(minutes=5) <= ts.astimezone(ET) <= scan_start + dt.timedelta(minutes=HEARTBEAT_GRACE_MIN)
    return ("OK", ts.isoformat()) if age_ok else ("FAIL", f"last_scan_ts={ts.isoformat()} 不在 {window} 窗口内")


def check_store(date_str: str, window: str) -> tuple[str, str, dict | None]:
    if not STORE_DB:
        return "SKIPPED", "WATCHDOG_STORE_DB 未配置", None
    try:
        con = sqlite3.connect(f"file:{STORE_DB}?mode=ro", uri=True, timeout=5)
        row = con.execute(
            "SELECT payload FROM events WHERE source='aether' AND kind='aether_scan' "
            "AND json_extract(payload,'$.label')='BFS sp500' "
            "AND json_extract(payload,'$.date')=? AND json_extract(payload,'$.window')=? "
            "ORDER BY id DESC LIMIT 1",
            (date_str, window),
        ).fetchone()
        con.close()
    except Exception as exc:
        return "FAIL", f"store 查询失败: {exc}", None
    if not row:
        return "FAIL", f"store 无 {date_str} {window} 的 BFS aether_scan", None
    return "OK", "到位", json.loads(row[0])


def check_integrity(payload: dict | None) -> tuple[str, str]:
    if payload is None:
        return "SKIPPED", "无 payload 可查(C2 未到位,断环已由 C2 记账,不重复计)"
    status = str(payload.get("status") or "")
    uni = payload.get("universe_size")
    if status != "ok":
        return "FAIL", f"status={status!r}"
    if isinstance(uni, int) and uni < UNIVERSE_MIN:
        return "FAIL", f"universe_size={uni} < {UNIVERSE_MIN}"
    # rows 为空 + status ok = 本轮无候选通过过滤,合法状态,不告警
    return "OK", f"status=ok · universe={uni} · rows={len(payload.get('rows') or [])}"


def check_telegram_evidence(date_str: str, window: str) -> tuple[str, str]:
    if not DRYRUN_LOG:
        return "SKIPPED", "WATCHDOG_DRYRUN_LOG 未配置(如实上报,不假装通过)"
    try:
        size = os.path.getsize(DRYRUN_LOG)
        with open(DRYRUN_LOG, "rb") as f:
            f.seek(max(0, size - LOG_TAIL_BYTES))
            tail = f.read().decode("utf-8", "replace")
    except Exception as exc:
        return "FAIL", f"日志不可读: {exc}"
    if TG_OK_MARKER in tail and date_str in tail:
        return "OK", f"日志尾部见 {TG_OK_MARKER!r} 与 {date_str}"
    return "FAIL", "日志尾部未见本窗口发送证据"


def llm_summary(facts: dict) -> str:
    """9B 异常摘要,尽力而为;任何失败返回空串,绝不阻断告警。"""
    if not LOCAL_LLM_URL:
        return ""
    try:
        body = {
            "model": LOCAL_LLM_MODEL,
            "messages": [
                {"role": "system", "content": "你是 BFS 线运维哨兵。基于给定检查事实用中文写不超过三句的异常摘要:定位哪一环断了、最可能的单一原因、建议的第一步动作。不得编造事实。"},
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
            "max_tokens": 200,
            "temperature": 0.2,
            "stream": False,
        }
        if LOCAL_LLM_MODEL == "demo/aster" or ":8501" in LOCAL_LLM_URL:
            from aether_grid_verify import attach_aster_chat_verification

            body = attach_aster_chat_verification(body, gateway_url=LOCAL_LLM_URL)
        data = _http_json(LOCAL_LLM_URL, data=body, timeout=10)
        return str(data["choices"][0]["message"]["content"]).strip()
    except Exception as exc:
        log.warning("9B summary failed (%s) — raw alert only", exc)
        return ""


def send_telegram(text: str) -> None:
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        log.warning("TELEGRAM_* 未配置,告警仅入 store")
        return
    try:
        _http_json(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception as exc:
        log.error("telegram send failed: %s", exc)


def emit_watchdog(payload: dict) -> None:
    try:
        _http_json(GRID_EVENTS, data={"source": "aether", "kind": "aether_watchdog", "payload": payload}, timeout=5)
    except Exception as exc:
        log.warning("store emit failed: %s", exc)


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def main() -> int:
    now_et = dt.datetime.now(ET)
    date_str = now_et.strftime("%Y-%m-%d")
    window = "AM" if now_et.hour < 12 else "PM"
    if not is_trading_day(now_et.date()):
        log.info("%s 非交易日,退出", date_str)
        return 0

    c1 = check_heartbeat(now_et, window)
    c2_status, c2_detail, payload = check_store(date_str, window)
    c3 = check_integrity(payload)
    c4 = check_telegram_evidence(date_str, window)

    checks = {
        "heartbeat": {"status": c1[0], "detail": c1[1]},
        "store": {"status": c2_status, "detail": c2_detail},
        "integrity": {"status": c3[0], "detail": c3[1]},
        "telegram": {"status": c4[0], "detail": c4[1]},
    }
    failed = [k for k, v in checks.items() if v["status"] == "FAIL"]
    overall = "alert" if failed else "ok"
    facts = {"date": date_str, "window": window, "checks": checks, "failed": failed}

    emit_watchdog({"date": date_str, "window": window, "status": overall, "checks": checks, "label": "BFS watchdog"})

    if not failed:
        log.info("%s %s 四环通过", date_str, window)
        return 0

    state = _load_state()
    fingerprint = f"{date_str}:{window}:{','.join(sorted(failed))}"
    if state.get("last_alert") == fingerprint:
        log.info("同指纹告警已发过,跳过重发: %s", fingerprint)
        return 1

    summary = llm_summary(facts)
    lines = [f"⚠️ BFS watchdog · {date_str} {window} · 断环: {', '.join(failed)}"]
    lines += [f"- {k}: {v['status']} · {v['detail']}" for k, v in checks.items()]
    if summary:
        lines += ["", f"9B: {summary}"]
    send_telegram("\n".join(lines))
    state["last_alert"] = fingerprint
    _save_state(state)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 哨兵不许静默死亡
        log.exception("watchdog internal error")
        send_telegram(f"⚠️ BFS watchdog 自身异常: {exc}")
        sys.exit(2)
