#!/usr/bin/env python3
"""SURFACE_DOCTOR v1 — 面板一致性自检(纯确定性,零 LLM,只读 store + HTTP 端点).

调度:09:58 / 15:48 ET(watchdog 之后 3 分钟).手动:`python surface_doctor.py --once`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo

from scan_quarantine import is_quarantined

ET = ZoneInfo("America/New_York")
STORE_DB = os.getenv("DOCTOR_STORE_DB", os.getenv("WATCHDOG_STORE_DB", ""))
GRID_EVENTS = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events")
PLATFORM_DECISIONS = os.getenv("DOCTOR_PLATFORM_DECISIONS", "http://127.0.0.1:8600/api/decisions")
PLATFORM_HEALTH = os.getenv("DOCTOR_PLATFORM_HEALTH", "http://127.0.0.1:8600/api/health")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_PATH = os.getenv(
    "DOCTOR_STATE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "surface_doctor_state.json"),
)
SKIP_LOG = os.getenv(
    "DOCTOR_QUARANTINE_SKIP_LOG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "quarantine_skip.jsonl"),
)
STALE_DEFAULT_S = int(os.getenv("DOCTOR_STALE_S", "900"))
STALE_MARKET_S = int(os.getenv("DOCTOR_STALE_MARKET_S", "300"))
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s surface_doctor %(levelname)s %(message)s")
log = logging.getLogger("surface_doctor")


def _http_json(url: str, *, data: dict | None = None, timeout: int = 10) -> Any:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method="POST" if body else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def is_trading_day(d: dt.date) -> bool:
    if d.weekday() >= 5:
        return False
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        return True
    try:
        key = d.isoformat()
        url = "https://paper-api.alpaca.markets/v2/calendar?" + urllib.parse.urlencode({"start": key, "end": key})
        data = _http_json(
            url,
            headers={"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY},
            timeout=5,
        )
        return any(e.get("date") == key for e in (data if isinstance(data, list) else []))
    except Exception as exc:
        log.warning("calendar unreachable (%s) — assume open", exc)
        return True


def store_scan_id(date_str: str, window: str) -> int | None:
    if not STORE_DB:
        return None
    con = sqlite3.connect(f"file:{STORE_DB}?mode=ro", uri=True, timeout=5)
    row = con.execute(
        "SELECT id FROM events WHERE source='aether' AND kind='aether_scan' "
        "AND json_extract(payload,'$.label')='BFS sp500' "
        "AND json_extract(payload,'$.date')=? AND json_extract(payload,'$.window')=? "
        "ORDER BY id DESC LIMIT 1",
        (date_str, window),
    ).fetchone()
    con.close()
    return int(row[0]) if row else None


def fetch_platform_decisions() -> dict | None:
    try:
        return _http_json(PLATFORM_DECISIONS, timeout=5)
    except Exception as exc:
        log.warning("platform decisions unreachable: %s", exc)
        return None


def fetch_platform_health() -> dict | None:
    try:
        return _http_json(PLATFORM_HEALTH, timeout=5)
    except Exception as exc:
        log.warning("platform health unreachable: %s", exc)
        return None


def _mid_entry(row: dict) -> float | None:
    bid, ask = row.get("bid"), row.get("ask")
    if bid is not None and ask is not None:
        try:
            b, a = float(bid), float(ask)
            if b > 0 and a > 0:
                return round((b + a) / 2, 2)
        except (TypeError, ValueError):
            pass
    prem = row.get("premium_dollars")
    if prem is not None:
        try:
            return float(prem)
        except (TypeError, ValueError):
            pass
    return None


def card_eligible(row: dict) -> bool:
    entry = _mid_entry(row)
    stop = row.get("stop") if row.get("stop") is not None else row.get("stop_price")
    target = row.get("target") if row.get("target") is not None else row.get("target_price")
    return entry is not None and stop is not None and target is not None


def check_c1(date_str: str, window: str, plat: dict | None) -> dict[str, Any]:
    store_id = store_scan_id(date_str, window)
    plat_id = None
    if plat:
        aw = (plat.get("audit") or {}).get("windows", {}).get(window, {})
        plat_id = aw.get("scan_event_id")
    watchdog_id = store_id
    ids = {"store": store_id, "platform": plat_id, "watchdog_store": watchdog_id}
    vals = [v for v in ids.values() if v is not None]
    ok = len(vals) >= 2 and len(set(vals)) == 1
    return {
        "status": "OK" if ok else "FAIL",
        "detail": ids if not ok else f"同 id #{store_id}",
        "ids": ids,
    }


def check_c2(window: str, plat: dict | None) -> dict[str, Any]:
    if not plat:
        return {"status": "FAIL", "detail": "platform /api/decisions 不可达"}
    audit = plat.get("audit") or {}
    aw = audit.get("windows", {}).get(window, {})
    if aw.get("quarantine"):
        return {"status": "OK", "detail": "quarantine 轮 · C2 计数守恒暂停"}
    bfs = plat.get("bfs") or {}
    header_hits = len((bfs.get("windows") or {}).get(window, {}).get("rows") or [])
    candidates = aw.get("candidates")
    if candidates is None:
        candidates = header_hits
    filtered = aw.get("filtered") or []
    decisions = aw.get("decisions", len(plat.get("rows") or []))
    filt_n = len(filtered)
    rhs = decisions + filt_n
    eq_ok = candidates == rhs
    reason_ok = True
    if decisions == 0 and candidates > 0 and not aw.get("quarantine"):
        reason_ok = filt_n > 0 and all(f.get("reason") for f in filtered)
    ok = candidates == header_hits and eq_ok and reason_ok
    detail = {
        "header_hits": header_hits,
        "candidates": candidates,
        "decisions": decisions,
        "filtered": filt_n,
        "sum_dec_filt": rhs,
        "filter_reasons": [f.get("reason") for f in filtered],
        "quarantine": aw.get("quarantine"),
    }
    return {"status": "OK" if ok else "FAIL", "detail": detail}


def check_c3(store_rows: list[dict], *, quarantine: bool) -> dict[str, Any]:
    if quarantine:
        return {"status": "OK", "detail": "quarantine 轮无卡上屏"}
    bad = []
    for r in store_rows:
        if not card_eligible(r):
            sym = r.get("sym") or r.get("symbol")
            if _mid_entry(r) is not None or r.get("score") is not None:
                bad.append({"sym": sym, "entry": _mid_entry(r), "stop": r.get("stop"), "target": r.get("target")})
    return {"status": "OK" if not bad else "FAIL", "detail": bad or "无可执行卡"}


def check_c4(date_str: str, now_et: dt.datetime) -> dict[str, Any]:
    if not STORE_DB:
        return {"status": "SKIPPED", "detail": "store 未配置"}
    con = sqlite3.connect(f"file:{STORE_DB}?mode=ro", uri=True, timeout=5)
    issues: list[str] = []
    post_cutoff = now_et.replace(hour=16, minute=40, second=0, microsecond=0)
    if now_et < post_cutoff:
        row = con.execute(
            "SELECT id, ts, payload FROM events WHERE source='aether' AND kind='aether_brief' "
            "AND json_extract(payload,'$.date')=? ORDER BY id DESC LIMIT 1",
            (date_str,),
        ).fetchone()
        if row:
            payload = json.loads(row[2])
            title = str(payload.get("title") or "")
            if "盘后" in title:
                issues.append(f"盘后槽过早 · brief #{row[0]} · title={title!r}")
    pre = con.execute(
        "SELECT id, ts, payload FROM events WHERE source='aether' AND kind='aether_premarket_deepseek' "
        "AND json_extract(payload,'$.date')=? ORDER BY id DESC LIMIT 1",
        (date_str,),
    ).fetchone()
    con.close()
    if pre:
        ts = float(pre[1])
        compile_et = dt.datetime.fromtimestamp(ts, tz=ET)
        if compile_et.date().isoformat() != date_str or not (compile_et.hour < 9 or (compile_et.hour == 9 and compile_et.minute < 30)):
            issues.append(
                f"盘前槽 compile 违规 · #{pre[0]} · {compile_et.strftime('%H:%M')} ET date={compile_et.date()}"
            )
    return {"status": "OK" if not issues else "FAIL", "detail": issues or "槽位时序 OK"}


def _skip_log_has_quarantine(scan_ids: list[int]) -> bool:
    if not os.path.isfile(SKIP_LOG):
        return False
    try:
        text = open(SKIP_LOG, encoding="utf-8").read()
    except OSError:
        return False
    return "quarantine" in text and any(str(i) in text for i in scan_ids)


def check_c5(date_str: str, window: str, plat: dict | None, scan_id: int | None) -> dict[str, Any]:
    q_active = is_quarantined(event_id=scan_id, date=date_str, window=window)
    if not q_active:
        return {"status": "OK", "detail": "无 quarantine 轮"}
    issues: list[str] = []
    if plat:
        q = plat.get("quarantine") or {}
        if not q.get("active"):
            issues.append("platform quarantine.active=false")
        hc = plat.get("header_contract") or {}
        if not hc.get("am_isolation_badge"):
            issues.append(f"platform 头部裸计数 · header={hc}")
        aw = (plat.get("audit") or {}).get("windows", {}).get(window, {})
        if not aw.get("quarantine"):
            issues.append("platform audit 未标 quarantine")
    scan_ids = list((plat or {}).get("quarantine", {}).get("scan_event_ids") or [])
    if scan_id and scan_id not in scan_ids:
        scan_ids.append(scan_id)
    if not _skip_log_has_quarantine(scan_ids):
        issues.append(f"paper skip 日志缺失 · {SKIP_LOG}")
    return {"status": "OK" if not issues else "FAIL", "detail": issues}


def check_c6(health: dict | None) -> dict[str, Any]:
    if not health:
        return {"status": "FAIL", "detail": "platform health 不可达"}
    comps = health.get("components") or {}
    yellow: list[str] = []
    for name, meta in comps.items():
        age_s = meta.get("age_s")
        if age_s is None:
            continue
        limit = STALE_MARKET_S if name in ("data_crypto", "data_equity") else STALE_DEFAULT_S
        if age_s > limit:
            yellow.append(f"{name} age={age_s}s>{limit}s")
    return {"status": "WARN" if yellow else "OK", "detail": yellow or "新鲜度 OK"}


def emit_doctor(payload: dict) -> None:
    try:
        _http_json(GRID_EVENTS, data={"source": "aether", "kind": "surface_doctor", "payload": payload}, timeout=5)
    except Exception as exc:
        log.warning("store emit failed: %s", exc)


def send_telegram(text: str) -> None:
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        log.warning("TELEGRAM_* 未配置")
        return
    try:
        _http_json(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception as exc:
        log.error("telegram failed: %s", exc)


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


def run_checks(*, date_str: str, window: str, now_et: dt.datetime | None = None) -> dict[str, Any]:
    now_et = now_et or dt.datetime.now(ET)
    plat = fetch_platform_decisions()
    health = fetch_platform_health()
    store_id = store_scan_id(date_str, window)
    store_rows: list[dict] = []
    if STORE_DB and store_id:
        con = sqlite3.connect(f"file:{STORE_DB}?mode=ro", uri=True, timeout=5)
        row = con.execute("SELECT payload FROM events WHERE id=?", (store_id,)).fetchone()
        con.close()
        if row:
            store_rows = json.loads(row[0]).get("rows") or []

    q_active = is_quarantined(event_id=store_id, date=date_str, window=window)
    checks = {
        "c1_same_scan_id": check_c1(date_str, window, plat),
        "c2_count_conservation": check_c2(window, plat),
        "c3_card_eligibility": check_c3(store_rows, quarantine=q_active),
        "c4_brief_slots": check_c4(date_str, now_et),
        "c5_quarantine": check_c5(date_str, window, plat, store_id),
        "c6_stale": check_c6(health),
    }
    red = [k for k, v in checks.items() if v["status"] == "FAIL"]
    yellow = [k for k, v in checks.items() if v["status"] == "WARN"]
    green = 6 - len(red) - len(yellow)
    overall = "alert" if red else ("warn" if yellow else "ok")
    return {
        "date": date_str,
        "window": window,
        "scan_id": store_id,
        "status": overall,
        "checks": checks,
        "failed": red,
        "warned": yellow,
        "green_count": green,
    }


def format_telegram(report: dict) -> str:
    if report["status"] == "ok":
        sid = report.get("scan_id") or "?"
        return f"面板体检 6/6 绿 · {report['window']} · #{sid}"
    lines = [f"⚠️ 面板体检 · {report['date']} {report['window']} · 红:{len(report['failed'])} 黄:{len(report['warned'])}"]
    for key in report["failed"] + report["warned"]:
        c = report["checks"][key]
        lines.append(f"- {key}: {c['status']} · {json.dumps(c['detail'], ensure_ascii=False)[:400]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="SURFACE_DOCTOR v1")
    parser.add_argument("--once", action="store_true", help="跑一次(忽略交易日可 --force)")
    parser.add_argument("--force", action="store_true", help="非交易日也跑")
    parser.add_argument("--window", choices=["AM", "PM"], help="指定窗口(默认按当前 ET 小时)")
    args = parser.parse_args()

    now_et = dt.datetime.now(ET)
    date_str = now_et.strftime("%Y-%m-%d")
    window = args.window or ("AM" if now_et.hour < 12 else "PM")
    if not args.force and not is_trading_day(now_et.date()):
        log.info("%s 非交易日,退出", date_str)
        return 0

    try:
        report = run_checks(date_str=date_str, window=window, now_et=now_et)
    except Exception as exc:
        log.exception("doctor internal error")
        send_telegram(f"⚠️ SURFACE_DOCTOR down: {exc}")
        return 2

    emit_doctor({**report, "label": "surface_doctor"})

    if report["status"] == "ok":
        send_telegram(format_telegram(report))
        log.info("6/6 绿")
        return 0

    fingerprint = f"{date_str}:{window}:{','.join(sorted(report['failed']))}"
    state = _load_state()
    if state.get("last_alert") != fingerprint:
        send_telegram(format_telegram(report))
        state["last_alert"] = fingerprint
        _save_state(state)
    else:
        log.info("同指纹跳过 Telegram: %s", fingerprint)
    return 1


if __name__ == "__main__":
    sys.exit(main())
