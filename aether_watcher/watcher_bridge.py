#!/usr/bin/env python3
"""
Watcher Bridge — 8520 Aether Watcher → 8501 Grid store 单向注入桥
================================================================
不变量（不可修改，改动视为架构违规）:
  1. 只 POST 不 GET —— 本文件不得出现任何读 store 的调用。
  2. report-only —— 注入的事件不入信号路径、不参与 scan/编译/journal。
  3. trade-action 词库为出桥第二道闸，词库与 contract_gate 同源。
  4. 专用 token（BRIDGE_STORE_TOKEN），仅此桥使用，吊销即断桥。

运行:  python3 watcher_bridge.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

BASE = Path(os.getenv("WATCHER_STATE_DIR", Path(__file__).parent / "state"))
EVENTS_FILE = BASE / "events.json"
CURSOR_FILE = BASE / "bridge_cursor.json"
DEADLETTER_FILE = BASE / "bridge_deadletter.jsonl"
HEARTBEAT_FILE = BASE / "heartbeat.json"

GRID_STORE_URL = os.getenv("GRID_STORE_URL", "http://127.0.0.1:8501/store/events")
BRIDGE_TOKEN = os.getenv("BRIDGE_STORE_TOKEN", "")

POLL_SEC = 30
MAX_RETRY = 5
HB_STALE_SEC = 120
HTTP_TIMEOUT = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bridge] %(levelname)s %(message)s",
)
log = logging.getLogger("watcher_bridge")

try:
    _gw = Path(__file__).resolve().parents[1] / "grid-sovereign-runtime" / "gateway"
    if str(_gw) not in sys.path:
        sys.path.insert(0, str(_gw))
    from contract_lexicon import TRADE_ACTION_OUTPUT  # type: ignore
except ImportError:
    TRADE_ACTION_OUTPUT = re.compile(
        r"建仓|做多|做空|买入|卖出|加仓|开仓|平仓|开多|开空|平多|平空|下单",
        re.I,
    )


def classify(ev: dict) -> str:
    kind = str(ev.get("kind", ""))
    target = str(ev.get("target", ""))
    if "Momentum" in kind or "momentum" in target.lower():
        return "watcher_momentum"
    if "health" in kind.lower() or "scanner" in target.lower() or kind == "watcher_health":
        return "watcher_health"
    return "watcher_alert"


def to_grid_event(ev: dict) -> dict:
    kind = classify(ev)
    note = ev.get("detail", "") or ""
    if ev.get("summary"):
        note = (note + "\n" + ev["summary"]).strip()
    payload = {
        "label": ev.get("kind", "watcher"),
        "note": note,
        "src_target": ev.get("target", ""),
        "src_time": ev.get("time", ""),
        "report_only": True,
        "origin": "8520",
    }
    if ev.get("sym"):
        payload["sym"] = ev["sym"]
    return {"source": "watcher", "kind": kind, "payload": payload}


def _rj(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _wj(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def event_key(ev: dict) -> str:
    return f"{ev.get('target','?')}|{ev.get('time','?')}|{ev.get('kind','?')}"


def post_batch(batch: list[dict]) -> bool:
    headers = {"Content-Type": "application/json"}
    if BRIDGE_TOKEN:
        headers["X-Grid-Token"] = BRIDGE_TOKEN
    delay = 1.0
    for attempt in range(1, MAX_RETRY + 1):
        try:
            ok_all = True
            for gev in batch:
                r = requests.post(
                    GRID_STORE_URL,
                    json=gev,
                    headers=headers,
                    timeout=HTTP_TIMEOUT,
                )
                if r.status_code in (401, 403):
                    log.error("token rejected (%s) — 桥停推，走 deadletter", r.status_code)
                    ok_all = False
                    break
                if r.status_code >= 400:
                    ok_all = False
                    break
            if ok_all:
                return True
        except requests.RequestException as e:
            log.warning("POST failed (attempt %d/%d): %s", attempt, MAX_RETRY, e)
        time.sleep(delay)
        delay = min(delay * 2, 30)
    with DEADLETTER_FILE.open("a", encoding="utf-8") as f:
        for gev in batch:
            f.write(json.dumps(gev, ensure_ascii=False) + "\n")
    log.error("batch dead-lettered (%d events)", len(batch))
    return False


_last_hb_alert = 0.0


def heartbeat_event() -> dict | None:
    global _last_hb_alert
    hb = _rj(HEARTBEAT_FILE, {})
    ts = hb.get("ts", 0)
    if not ts:
        return None
    age = time.time() - ts
    if age > HB_STALE_SEC and time.time() - _last_hb_alert > 600:
        _last_hb_alert = time.time()
        return {
            "source": "watcher",
            "kind": "watcher_health",
            "payload": {
                "label": "heartbeat_stale",
                "note": f"WARN watcher 心跳停止 {int(age)}s — daemon 可能挂了",
                "report_only": True,
                "origin": "8520",
            },
        }
    return None


def run():
    log.info(
        "bridge up · %s → %s · poll %ds · 只POST不GET",
        EVENTS_FILE,
        GRID_STORE_URL,
        POLL_SEC,
    )
    cursor: dict = _rj(CURSOR_FILE, {"seen": []})
    seen = set(cursor.get("seen", []))

    while True:
        try:
            events = _rj(EVENTS_FILE, [])
            fresh = [e for e in events if event_key(e) not in seen]

            batch = []
            for ev in fresh:
                gev = to_grid_event(ev)
                if TRADE_ACTION_OUTPUT.search(gev["payload"].get("note", "")):
                    log.warning("blocked by trade-action lexicon: %s", event_key(ev))
                    seen.add(event_key(ev))
                    continue
                batch.append(gev)

            hb_ev = heartbeat_event()
            if hb_ev:
                batch.append(hb_ev)

            if batch:
                if post_batch(batch):
                    log.info("pushed %d events", len(batch))
                for ev in fresh:
                    seen.add(event_key(ev))
                cursor["seen"] = list(seen)[-2000:]
                _wj(CURSOR_FILE, cursor)
        except Exception as e:
            log.error("bridge loop error: %s", e)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    run()
