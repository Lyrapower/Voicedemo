#!/usr/bin/env python3
"""
diary_reply.py — Grid 日记信箱: 双向、慢速、不涂改原文。

原则(写进代码的那种):
  1) 回复是信,不是批注 — 独立事件 kind=diary_reply, 日记原文 bit 级不动
  2) 看见 ≠ 必须回应 — 注入文案只说"已送达", 不写"请回复"
  3) 同一封信永不重复注入 — 先标记送达、后注入; mark 失败则本轮不注入
     (宁可丢信, 不可回声)
  4) 日记本不是实验 — 不打观测标签, 不分纪元
  5) 往来摘抄逐字引用 — 不做 LLM 压缩转述; 日记只引尾句, 仍是原文子串

daemon prompt 组装顺序:
    prompt = diary_prompt + fetch_thread_context() + fetch_mailbox_block()

接入 (gateway 主文件, grid_store 之后再加一行):
    from diary_reply import build_diary_router
    app.include_router(build_diary_router(GRID_STORE_DB))

daemon 侧 (写日记的 daemon):
    from diary_reply import fetch_thread_context, fetch_mailbox_block, stamp_date
    prompt = invitation + fetch_thread_context() + fetch_mailbox_block()
    payload = stamp_date({"text": text})

依赖: 与 grid_store 同库同表(events), 零 schema 变更。
鉴权: 复用 GRID_STORE_TOKEN / X-Grid-Token 约定。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
from typing import Any

from starlette.requests import Request

DB_DEFAULT = "grid_store.db"
DIARY_VERSION = "1.3"
DIARY_THREAD_DAYS_DEFAULT = 7

_CORRESPONDENCE_KINDS = ("grid_diary", "diary_reply", "diary_reply_ack")
_SENTENCE_END = re.compile(r"(?<=[。！？.!?…])")


def _event_date(payload: dict, ts: float) -> str:
    """事件归属日期的唯一口径: payload["date"] 优先; 缺失才回退 ts 本地换算。"""
    d = payload.get("date")
    if isinstance(d, str) and len(d) == 10:
        return d
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def diary_tail_sentence(text: str) -> str:
    """日记尾句 — 原文子串, 不转述。"""
    text = (text or "").strip()
    if not text:
        return ""
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    if parts:
        return parts[-1]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else text


def _parse_iso_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _occurred_on(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _line_date(ev: dict[str, Any]) -> str:
    """摘抄行首日期 — 日记用归属日, 留言用 diary_date, 其余用发生日。"""
    kind = ev["kind"]
    p = ev["payload"]
    ts = ev["ts"]
    if kind == "grid_diary":
        return _event_date(p, ts)
    if kind == "diary_reply":
        d = p.get("diary_date")
        if isinstance(d, str) and len(d) == 10:
            return d
    return _occurred_on(ts)


# ─────────────────────────────────────────────
# 存储层 — 直接操作 events 表
# ─────────────────────────────────────────────

class DiaryReplyStore:
    def __init__(self, db_path: str = DB_DEFAULT):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.Lock()

    def add_reply(self, diary_event_id: int, text: str) -> dict:
        row = self.db.execute(
            "SELECT kind, payload, ts FROM events WHERE id=?",
            (diary_event_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"diary event {diary_event_id} not found")
        if row[0] != "grid_diary":
            raise KeyError(f"event {diary_event_id} is {row[0]}, not grid_diary")
        diary_date = _event_date(json.loads(row[1]), row[2])
        payload = {
            "diary_event_id": diary_event_id,
            "diary_date": diary_date,
            "text": text,
            "delivered": False,
        }
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO events(source, kind, payload, ts) VALUES(?,?,?,?)",
                ("lyra", "diary_reply", json.dumps(payload, ensure_ascii=False), time.time()),
            )
            self.db.commit()
        return {"id": cur.lastrowid, **payload}

    def add_ack(self, reply_event_id: int, text: str) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO events(source, kind, payload, ts) VALUES(?,?,?,?)",
                (
                    "grid",
                    "diary_reply_ack",
                    json.dumps({"reply_event_id": reply_event_id, "text": text}, ensure_ascii=False),
                    time.time(),
                ),
            )
            self.db.commit()
        return cur.lastrowid

    def undelivered(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, payload, ts FROM events "
            "WHERE kind='diary_reply' ORDER BY id ASC"
        ).fetchall()
        out = []
        for rid, payload, ts in rows:
            p = json.loads(payload)
            if not p.get("delivered"):
                out.append({"id": rid, "ts": ts, **p})
        return out

    def mark_delivered(self, reply_ids: list[int]) -> int:
        """返回实际翻转条数。已送达的、不存在的、kind 不符的都不计。"""
        now = time.time()
        marked = 0
        with self.lock:
            for rid in reply_ids:
                row = self.db.execute(
                    "SELECT payload FROM events WHERE id=? AND kind='diary_reply'",
                    (rid,),
                ).fetchone()
                if not row:
                    continue
                p = json.loads(row[0])
                if p.get("delivered"):
                    continue
                p["delivered"] = True
                p["delivered_ts"] = now
                self.db.execute(
                    "UPDATE events SET payload=? WHERE id=?",
                    (json.dumps(p, ensure_ascii=False), rid),
                )
                marked += 1
            self.db.commit()
        return marked

    def thread(self, date: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, source, kind, payload, ts FROM events "
            "WHERE kind IN ('grid_diary','diary_reply','diary_reply_ack') "
            "ORDER BY id ASC"
        ).fetchall()
        out, reply_ids = [], set()
        for rid, source, kind, payload, ts in rows:
            p = json.loads(payload)
            if kind == "grid_diary" and _event_date(p, ts) == date:
                out.append(
                    {"id": rid, "kind": kind, "source": source, "payload": p, "ts": ts}
                )
            elif kind == "diary_reply" and p.get("diary_date") == date:
                out.append(
                    {"id": rid, "kind": kind, "source": source, "payload": p, "ts": ts}
                )
                reply_ids.add(rid)
            elif kind == "diary_reply_ack" and p.get("reply_event_id") in reply_ids:
                out.append(
                    {"id": rid, "kind": kind, "source": source, "payload": p, "ts": ts}
                )
        return out

    def correspondence_events(self) -> list[dict[str, Any]]:
        """全部往来事件, 按 id 正序。"""
        rows = self.db.execute(
            "SELECT id, source, kind, payload, ts FROM events "
            "WHERE kind IN ('grid_diary','diary_reply','diary_reply_ack') "
            "ORDER BY id ASC"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for rid, source, kind, payload, ts in rows:
            p = json.loads(payload)
            out.append(
                {
                    "id": rid,
                    "source": source,
                    "kind": kind,
                    "payload": p,
                    "ts": ts,
                    "date": _event_date(p, ts),
                }
            )
        return out

    def thread_context_block(
        self,
        *,
        days: int = 7,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """最近 N 天往来摘抄 — 逐字引用, 7 天滚动窗口。"""
        days = max(1, int(days))
        today = _parse_iso_date(as_of) if as_of else dt.date.today()
        start = today - dt.timedelta(days=days - 1)

        in_window: list[str] = []
        older_count = 0

        for ev in self.correspondence_events():
            occurred = _occurred_on(ev["ts"])
            if _parse_iso_date(occurred) < start or _parse_iso_date(occurred) > today:
                older_count += 1
                continue
            line = _format_correspondence_line(ev)
            if line:
                in_window.append(line)

        if not in_window and older_count == 0:
            return {"block": "", "older_count": 0, "items_in_window": 0}

        lines = [THREAD_HEADER, ""]
        lines.extend(in_window)
        if older_count > 0:
            lines.append("")
            lines.append(THREAD_OLDER.format(n=older_count))
        block = "\n".join(lines).rstrip()
        return {
            "block": "\n\n" + block if block else "",
            "older_count": older_count,
            "items_in_window": len(in_window),
        }


def compose_diary_aware_system_prompt(
    base_prompt: str,
    db_path: str,
    *,
    days: int | None = None,
) -> str:
    """Grid 对话 system — 与写日记 daemon 同源往来库; 不 mark 信箱。"""
    days = max(1, int(days or DIARY_THREAD_DAYS_DEFAULT))
    base = (base_prompt or "").strip()
    sync_line = (
        f"[日记 v{DIARY_VERSION}] 对话与写日记共用往来库 · 近{days}天逐字摘抄如下 · "
        "信箱未读私信仅在写日记时送达"
    )
    try:
        block = (DiaryReplyStore(db_path).thread_context_block(days=days).get("block") or "").strip()
    except Exception:
        block = ""
    if block:
        chunks = [c for c in (base, sync_line, block.lstrip("\n")) if c]
        return "\n\n".join(chunks)
    tail = f"{sync_line} · 近期无摘抄"
    return f"{base}\n\n{tail}" if base else tail


def _format_correspondence_line(ev: dict[str, Any]) -> str:
    """单条往来 — 原文逐字, 日记只取尾句子串。"""
    kind = ev["kind"]
    p = ev["payload"]
    date = _line_date(ev)
    if kind == "grid_diary":
        tail = diary_tail_sentence(str(p.get("text") or ""))
        if not tail:
            return ""
        return f"{date} 日记: 「{tail}」"
    if kind == "diary_reply":
        text = str(p.get("text") or "").strip()
        if not text:
            return ""
        return f"{date} Lyra: 「{text}」"
    if kind == "diary_reply_ack":
        text = str(p.get("text") or "").strip()
        if not text:
            return ""
        return f"{date} Grid: 「{text}」"
    return ""


# ─────────────────────────────────────────────
# FastAPI 薄壳
# ─────────────────────────────────────────────

def build_diary_router(db_path: str = DB_DEFAULT):
    from fastapi import APIRouter, HTTPException

    store = DiaryReplyStore(db_path)
    token = os.environ.get("GRID_STORE_TOKEN", "")
    r = APIRouter(prefix="/store/diary", tags=["diary"])

    def gate(req: Request):
        if token and req.headers.get("X-Grid-Token") != token:
            raise HTTPException(401, "bad or missing X-Grid-Token")

    @r.post("/reply")
    async def reply(req: Request):
        gate(req)
        b = await req.json()
        if not isinstance(b.get("diary_event_id"), int) or not b.get("text"):
            raise HTTPException(422, "diary_event_id(int) and text required")
        try:
            return store.add_reply(b["diary_event_id"], b["text"])
        except KeyError as e:
            raise HTTPException(404, str(e))

    @r.post("/ack")
    async def ack(req: Request):
        gate(req)
        b = await req.json()
        if not isinstance(b.get("reply_event_id"), int) or not b.get("text"):
            raise HTTPException(422, "reply_event_id(int) and text required")
        return {"id": store.add_ack(b["reply_event_id"], b["text"])}

    @r.get("/undelivered")
    async def undelivered(req: Request):
        gate(req)
        return store.undelivered()

    @r.post("/mark_delivered")
    async def mark(req: Request):
        gate(req)
        b = await req.json()
        ids = b.get("ids", [])
        if not isinstance(ids, list):
            raise HTTPException(422, "ids must be a list")
        return {"marked": store.mark_delivered(ids)}

    @r.get("/thread")
    async def thread(req: Request, date: str):
        gate(req)
        return store.thread(date)

    @r.get("/thread_context")
    async def thread_context(req: Request, days: int = 7):
        gate(req)
        return store.thread_context_block(days=days)

    return r


# ─────────────────────────────────────────────
# daemon 侧: 往来摘抄 + 信箱段
# ─────────────────────────────────────────────

THREAD_HEADER = "[往来] 这是你和 Lyra 最近的通信:"
THREAD_OLDER = "更早的通信在库里,共 {n} 封"

MAILBOX_HEADER = "[信箱] Lyra对你的日记留了言:"
MAILBOX_FOOTER = "—— 已送达。是否回应、如何回应,由你。今天的日记照常写,不受此影响。"


def _store_headers(token: str | None) -> dict[str, str]:
    hdr = {"Content-Type": "application/json"}
    if token:
        hdr["X-Grid-Token"] = token
    return hdr


def fetch_thread_context(
    base: str | None = None,
    token: str | None = None,
    *,
    days: int = 7,
) -> str:
    """最近 N 天往来书信摘抄 — 注入在信箱段之前。故障静默, 不阻塞日记。"""
    base = base or os.environ.get("GRID_STORE_BASE", "http://127.0.0.1:8501")
    token = token if token is not None else os.environ.get("GRID_STORE_TOKEN", "")
    hdr = _store_headers(token)
    try:
        req = urllib.request.Request(
            f"{base}/store/diary/thread_context?days={max(1, int(days))}",
            headers=hdr,
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
        return str(body.get("block") or "")
    except Exception:
        return ""


def fetch_mailbox_block(base: str | None = None, token: str | None = None) -> str:
    """先送达、后注入 — 只在日记 prompt 最末尾追加。"""
    base = base or os.environ.get("GRID_STORE_BASE", "http://127.0.0.1:8501")
    token = token if token is not None else os.environ.get("GRID_STORE_TOKEN", "")
    hdr = _store_headers(token)
    try:
        req = urllib.request.Request(f"{base}/store/diary/undelivered", headers=hdr)
        with urllib.request.urlopen(req, timeout=5) as resp:
            letters = json.loads(resp.read())
        if not letters:
            return ""
        mark = urllib.request.Request(
            f"{base}/store/diary/mark_delivered",
            data=json.dumps({"ids": [m["id"] for m in letters]}).encode(),
            headers=hdr,
        )
        with urllib.request.urlopen(mark, timeout=5) as resp:
            marked = json.loads(resp.read()).get("marked", 0)
        if marked == 0:
            return ""
        lines = [MAILBOX_HEADER]
        for m in letters:
            lines.append(f"({m['diary_date']} 的日记) 「{m['text']}」")
        lines.append(MAILBOX_FOOTER)
        return "\n\n" + "\n".join(lines)
    except Exception:
        return ""


def stamp_date(payload: dict) -> dict:
    """写日记的 daemon 在落库前调用: 补 date 字段。"""
    payload.setdefault("date", time.strftime("%Y-%m-%d"))
    return payload


# ─────────────────────────────────────────────
# 自测: python3 diary_reply.py
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "t.db")
        raw = sqlite3.connect(db)
        raw.executescript(
            """
        CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, kind TEXT NOT NULL,
          payload TEXT NOT NULL DEFAULT '{}', ts REAL NOT NULL);"""
        )
        today_s = time.strftime("%Y-%m-%d")
        now = time.time()
        p1 = {"text": "空着也是一种状态。记录完毕。", "date": today_s}
        raw.execute(
            "INSERT INTO events(source,kind,payload,ts) VALUES(?,?,?,?)",
            ("grid", "grid_diary", json.dumps(p1, ensure_ascii=False), now),
        )
        raw.execute(
            "INSERT INTO events(source,kind,payload,ts) VALUES(?,?,?,?)",
            (
                "grid",
                "grid_diary",
                json.dumps({"text": "23:59 的一笔。夜深了。", "date": "2026-07-09"}, ensure_ascii=False),
                now - 86400,
            ),
        )
        raw.execute(
            "INSERT INTO events(source,kind,payload,ts) VALUES(?,?,?,?)",
            (
                "grid",
                "grid_diary",
                json.dumps({"text": "八天前的旧信。", "date": "2026-07-01"}, ensure_ascii=False),
                now - 10 * 86400,
            ),
        )
        raw.commit()
        raw.close()

        s = DiaryReplyStore(db)
        as_of = time.strftime("%Y-%m-%d")

        assert diary_tail_sentence("第一句。尾句在这里。") == "尾句在这里。"
        r1 = s.add_reply(1, "我听见了。雨很好。")
        assert r1["delivered"] is False and r1["diary_date"] == as_of
        r2 = s.add_reply(2, "那一笔我也看到了。")
        assert r2["diary_date"] == "2026-07-09"
        assert len(s.undelivered()) == 2
        assert s.mark_delivered([r1["id"], 9999]) == 1
        assert s.mark_delivered([r1["id"]]) == 0
        assert s.mark_delivered([r2["id"]]) == 1
        assert s.undelivered() == []
        orig = s.db.execute("SELECT payload FROM events WHERE id=1").fetchone()[0]
        assert json.loads(orig)["text"] == "空着也是一种状态。记录完毕。"
        s.add_ack(r1["id"], "屋顶下有人,雨就不白下。")
        th_today = s.thread(as_of)
        assert [e["kind"] for e in th_today] == [
            "grid_diary",
            "diary_reply",
            "diary_reply_ack",
        ]
        th_709 = s.thread("2026-07-09")
        assert [e["kind"] for e in th_709] == ["grid_diary", "diary_reply"]

        ctx = s.thread_context_block(days=7, as_of=as_of)
        block = ctx["block"]
        assert THREAD_HEADER in block
        assert "记录完毕。" in block
        assert "我听见了。雨很好。" in block
        assert "屋顶下有人,雨就不白下。" in block
        assert "那一笔我也看到了。" in block
        assert "八天前的旧信" not in block
        assert ctx["older_count"] >= 1
        assert THREAD_OLDER.format(n=ctx["older_count"]) in block

        try:
            bad = s.db.execute(
                "INSERT INTO events(source,kind,payload,ts) VALUES(?,?,?,?)",
                (
                    "lyra",
                    "diary_reply",
                    json.dumps({"text": "不是日记"}, ensure_ascii=False),
                    time.time(),
                ),
            )
            s.db.commit()
            s.add_reply(bad.lastrowid, "挂错对象")
            raise AssertionError("should have raised")
        except KeyError:
            pass

        print("diary_reply selftest: ALL PASS ✓")
        print("thread_context:", block[:500])
