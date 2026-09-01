"""Tests for Grid diary reply + thread context."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import datetime as dt
from pathlib import Path

GATEWAY = Path(__file__).resolve().parent
sys.path.insert(0, str(GATEWAY))

from diary_reply import (  # noqa: E402
    DIARY_VERSION,
    THREAD_HEADER,
    THREAD_OLDER,
    DiaryReplyStore,
    compose_diary_aware_system_prompt,
    diary_tail_sentence,
    stamp_date,
)


def test_diary_tail_sentence_verbatim():
    src = "第一句。尾句在这里。"
    assert diary_tail_sentence(src) == "尾句在这里。"
    assert diary_tail_sentence(src) in src


def test_thread_context_seven_day_window(tmp_path):
    db = tmp_path / "t.db"
    raw = sqlite3.connect(db)
    raw.executescript(
        """
        CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, kind TEXT NOT NULL,
          payload TEXT NOT NULL DEFAULT '{}', ts REAL NOT NULL);"""
    )
    now = time.time()
    for i, (date, text, ts_off) in enumerate(
        [
            (time.strftime("%Y-%m-%d"), "今天很好。收工。", 0),
            ((dt.date.today() - dt.timedelta(days=1)).isoformat(), "昨天。睡了。", 86400),
            ((dt.date.today() - dt.timedelta(days=10)).isoformat(), "很久以前。忘了。", 10 * 86400),
        ]
    ):
        raw.execute(
            "INSERT INTO events(source,kind,payload,ts) VALUES(?,?,?,?)",
            (
                "grid",
                "grid_diary",
                json.dumps({"text": text, "date": date}, ensure_ascii=False),
                now - ts_off,
            ),
        )
    raw.commit()
    raw.close()

    s = DiaryReplyStore(str(db))
    s.add_reply(1, "今天看见了。")
    s.add_ack(2, "嗯。")

    ctx = s.thread_context_block(days=7, as_of=time.strftime("%Y-%m-%d"))
    block = ctx["block"]
    assert THREAD_HEADER in block
    assert "收工。" in block
    assert "今天看见了。" in block
    assert "嗯。" in block
    assert "忘了。" not in block
    assert ctx["older_count"] == 1
    assert THREAD_OLDER.format(n=1) in block


def test_compose_diary_aware_system_prompt_includes_thread(tmp_path):
    db = tmp_path / "t.db"
    raw = sqlite3.connect(db)
    raw.executescript(
        """
        CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, kind TEXT NOT NULL,
          payload TEXT NOT NULL DEFAULT '{}', ts REAL NOT NULL);"""
    )
    raw.execute(
        "INSERT INTO events(source,kind,payload,ts) VALUES(?,?,?,?)",
        (
            "grid",
            "grid_diary",
            json.dumps({"text": "今天。收工。", "date": time.strftime("%Y-%m-%d")}, ensure_ascii=False),
            time.time(),
        ),
    )
    raw.commit()
    raw.close()
    out = compose_diary_aware_system_prompt("BASE", str(db))
    assert "BASE" in out
    assert f"v{DIARY_VERSION}" in out
    assert "收工。" in out
    assert THREAD_HEADER in out


def test_empty_thread_returns_empty_block(tmp_path):
    db = tmp_path / "t.db"
    sqlite3.connect(db).executescript(
        """
        CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, kind TEXT NOT NULL,
          payload TEXT NOT NULL DEFAULT '{}', ts REAL NOT NULL);"""
    )
    ctx = DiaryReplyStore(str(db)).thread_context_block(days=7, as_of="2026-07-10")
    assert ctx["block"] == ""
    assert ctx["older_count"] == 0
