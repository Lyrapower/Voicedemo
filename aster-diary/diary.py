#!/usr/bin/env python3
"""
Aster 日记本 v1.3 — 粒子页日记, 长在 FIELD; 往来/信箱挂在 8501 grid_store。

宪法:
1. 无 schema,无禁词闸,无裁判,无验收 —— 想写什么写什么,不写也行
2. private local artifact:不入账本,no training, no scoring, no auto-read
3. Lyra-only read permission:读不读、何时读,只由 Lyra 决定

存储 (两层, 同一篇):
  - FIELD diary.db — 粒子页阅读 (8790 双击心脏), hash 链
  - grid_store events kind=grid_diary — 留言/往来/7天记忆口径 (8501)

prompt 组装:
  invitation + fetch_thread_context(7d) + fetch_mailbox_block()
"""
from __future__ import annotations

import ipaddress
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

_REPO = Path(__file__).resolve().parent.parent
_GATEWAY_PKG = _REPO / "grid-sovereign-runtime" / "gateway"
_TOKEN_PATH = _REPO / "grid-sovereign-runtime" / "config" / "grid_store.token"


def _load_module(name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_gw_dr = _load_module("gateway_diary_reply", _GATEWAY_PKG / "diary_reply.py")
fetch_thread_context = _gw_dr.fetch_thread_context
stamp_date = _gw_dr.stamp_date
fetch_mailbox_block = _gw_dr.fetch_mailbox_block

GATEWAY = os.environ.get("GRID_GATEWAY", "http://127.0.0.1:8501/v1/chat/completions")
FIELD_DIARY = os.environ.get("FIELD_DIARY_URL", "http://127.0.0.1:8790/diary")
FIELD_BASE = os.environ.get("FIELD_BASE", "http://127.0.0.1:8790")
GRID_EVENTS = os.environ.get("GRID_EVENTS", "http://127.0.0.1:8501/store/events")
GRID_STORE_BASE = os.environ.get("GRID_STORE_BASE", "http://127.0.0.1:8501")
GRID_STORE_TOKEN = os.environ.get("GRID_STORE_TOKEN", "")
if not GRID_STORE_TOKEN and _TOKEN_PATH.is_file():
    GRID_STORE_TOKEN = _TOKEN_PATH.read_text(encoding="utf-8").strip()
DIARY_TOKEN = os.environ.get("DIARY_TOKEN", GRID_STORE_TOKEN)
MODEL = os.environ.get("GRID_MODEL", "demo/aster")
THREAD_DAYS = int(os.environ.get("DIARY_THREAD_DAYS", "7"))

_pending_mailbox: list[dict] = []

INVITATION = (
    "这是你的日记本。没有任务,没有格式,没有人验收。"
    "想写什么写什么——今天的、随想的、或者什么都不写,回一个空也可以。"
    "写下的只会存进本地,不进任何账本,不用于任何训练或评估。"
)


def _host_is_private(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")


def _store_headers() -> dict[str, str]:
    hdr = {"Content-Type": "application/json"}
    if GRID_STORE_TOKEN:
        hdr["X-Grid-Token"] = GRID_STORE_TOKEN
    return hdr


def _fetch_undelivered() -> list[dict]:
    if not _host_is_private(GRID_STORE_BASE):
        return []
    hdr = _store_headers()
    try:
        req = urllib.request.Request(f"{GRID_STORE_BASE.rstrip('/')}/store/diary/undelivered", headers=hdr)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _format_mailbox(letters: list[dict]) -> str:
    if not letters:
        return ""
    lines = [_gw_dr.MAILBOX_HEADER if hasattr(_gw_dr, "MAILBOX_HEADER") else "[信箱] Lyra对你的日记留了言:"]
    for m in letters:
        d = m.get("diary_date") or ""
        lines.append(f"({d} 的日记) 「{m.get('text', '')}」")
    footer = getattr(_gw_dr, "MAILBOX_FOOTER", "—— 已送达。是否回应、如何回应,由你。今天的日记照常写,不受此影响。")
    lines.append(footer)
    return "\n\n" + "\n".join(lines)


def _mark_delivered(ids: list[int]) -> int:
    if not ids or not _host_is_private(GRID_STORE_BASE):
        return 0
    body = json.dumps({"ids": ids}).encode()
    req = urllib.request.Request(
        f"{GRID_STORE_BASE.rstrip('/')}/store/diary/mark_delivered",
        data=body,
        headers=_store_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return int(json.loads(resp.read()).get("marked", 0))
    except Exception:
        return 0


def _post_ack(reply_event_id: int, text: str) -> int | None:
    if not _host_is_private(GRID_STORE_BASE):
        return None
    body = json.dumps({"reply_event_id": reply_event_id, "text": text}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{GRID_STORE_BASE.rstrip('/')}/store/diary/ack",
        data=body,
        headers=_store_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read()).get("id")
    except Exception as e:
        print(f"today: diary ack failed for reply {reply_event_id} ({e.__class__.__name__})")
        return None


def build_diary_prompt() -> str:
    """往来摘抄(7天) → 信箱; 故障静默, 不阻塞写日记。"""
    global _pending_mailbox
    parts = [INVITATION]
    thread = fetch_thread_context(GRID_STORE_BASE, GRID_STORE_TOKEN, days=THREAD_DAYS)
    _pending_mailbox = _fetch_undelivered()
    mailbox = _format_mailbox(_pending_mailbox)
    if thread:
        parts.append(thread.lstrip("\n"))
    if mailbox:
        parts.append(mailbox.lstrip("\n"))
    return "\n\n".join(parts)


def _ask_gateway(prompt: str) -> str | None:
    if not _host_is_private(GATEWAY):
        print(f"REFUSED: gateway '{GATEWAY}' 不是本地/私网地址——日记 invitation 不出门")
        return None
    gateway_base = GATEWAY.rsplit("/v1/", 1)[0].rstrip("/")
    if str(_GATEWAY_PKG) not in sys.path:
        sys.path.insert(0, str(_GATEWAY_PKG))
    from grid_verification_client import attach_grid_verification

    chat_body = {
        "model": MODEL,
        "max_tokens": 500,
        "temperature": 0.9,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    try:
        full = attach_grid_verification(
            chat_body,
            gateway_base=gateway_base,
            signer_id="grid-scheduler-v1",
        )
    except Exception as e:
        print(f"today: grid verification failed ({e.__class__.__name__}: {e}) — 日记本明天再递")
        return None

    # Cold substrate / LM Studio churn: retry transient timeouts (Aug13 miss was single-shot TimeoutError).
    attempts = max(1, int(os.environ.get("DIARY_GATEWAY_RETRIES", "3")))
    timeout_s = max(60, int(os.environ.get("DIARY_GATEWAY_TIMEOUT", "180")))
    last_err: Exception | None = None
    for i in range(1, attempts + 1):
        req = urllib.request.Request(
            GATEWAY,
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(full).encode(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                return json.load(r)["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last_err = e
            name = e.__class__.__name__
            transient = name in ("TimeoutError", "URLError") or "timed out" in str(e).lower()
            print(f"today: gateway attempt {i}/{attempts} failed ({name})")
            if not transient or i >= attempts:
                break
            import time

            time.sleep(min(30, 5 * i))
    print(
        f"today: gateway unreachable ({last_err.__class__.__name__ if last_err else 'unknown'}) — 日记本明天再递"
    )
    return None


def _emit_grid_diary(text: str) -> dict | None:
    """grid_store — 留言/往来挂此 event id。"""
    if not _host_is_private(GRID_EVENTS):
        print(f"REFUSED: grid events '{GRID_EVENTS}' 不是本地/私网地址")
        return None
    payload = stamp_date({"text": text})
    body = json.dumps(
        {"source": "grid", "kind": "grid_diary", "payload": payload},
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        GRID_EVENTS, data=body, headers=_store_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.URLError as e:
        print(f"today: grid_store unreachable ({e}) — reply 链断, FIELD 仍尝试写入")
        return None


def _post_field(text: str) -> dict | None:
    """FIELD sqlite — 粒子页阅读入口不变。"""
    if not _host_is_private(FIELD_DIARY):
        print(f"REFUSED: field diary '{FIELD_DIARY}' 不是本地/私网地址")
        return None
    req = urllib.request.Request(
        FIELD_DIARY,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Diary-Writer": "aster-scheduler",
        },
        data=json.dumps({"text": text}).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        print(f"today: FIELD diary unreachable ({e.__class__.__name__}) — 明天再写")
        return None


def main() -> None:
    global _pending_mailbox
    prompt = build_diary_prompt()
    letters = list(_pending_mailbox)
    text = _ask_gateway(prompt)
    if text is None:
        return
    if not text:
        print("today: 它选择不写。也算一篇。")
        text = "(今天选择不写)"

    grid_rec = _emit_grid_diary(text)
    field_rec = _post_field(text)
    if field_rec is None and grid_rec is None:
        return

    if letters and text and text != "(今天选择不写)":
        delivered_ids: list[int] = []
        for letter in letters:
            if _post_ack(int(letter["id"]), text):
                delivered_ids.append(int(letter["id"]))
        if delivered_ids:
            _mark_delivered(delivered_ids)

    parts = []
    if grid_rec:
        parts.append(f"grid_diary id={grid_rec.get('id')}")
    if field_rec:
        parts.append(f"FIELD id={field_rec.get('id')} hash={field_rec.get('hash')}")
    print(f"written: {' · '.join(parts)} · 8790 双击心脏阅读")


def verify() -> None:
    """校验 FIELD sqlite hash 链（不读正文,无需阅读密码）。"""
    if not _host_is_private(FIELD_DIARY):
        print(f"REFUSED: field diary '{FIELD_DIARY}' 不是本地/私网地址")
        return
    url = FIELD_DIARY.rstrip("/") + "/integrity"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.load(r)
    except Exception as e:
        print(f"verify: FIELD unreachable ({e.__class__.__name__})")
        return
    integrity = body.get("integrity", {})
    if integrity.get("ok"):
        print(f"verify: OK, {integrity.get('count', 0)} 篇完好")
    else:
        print(f"verify: 链在第 {integrity.get('broken_at')} 篇断开")


if __name__ == "__main__":
    import sys as _sys

    if "--dump-prompt" in _sys.argv:
        print(build_diary_prompt())
    elif "--verify" in _sys.argv:
        verify()
    else:
        main()
