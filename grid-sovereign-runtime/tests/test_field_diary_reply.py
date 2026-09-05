#!/usr/bin/env python3
"""Integration checks for field diary reply on canonical diary.db."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest

# gateway modules
GS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "gateway"))
sys.path.insert(0, GS)

from field_diary_reply import DiaryReplyStore  # noqa: E402


class FieldDiaryReplyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.temp.name, "diary.db")
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE entries(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
            "text TEXT NOT NULL, prev_hash TEXT, hash TEXT NOT NULL)"
        )
        ts = "2026-07-11T22:30:20"
        digest = hashlib.sha256((ts + "信号很轻。").encode()).hexdigest()
        conn.execute(
            "INSERT INTO entries(ts,text,prev_hash,hash) VALUES(?,?,?,?)",
            (ts, "信号很轻。", "", digest),
        )
        conn.commit()
        conn.close()
        self.store = DiaryReplyStore(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_lease_ack_after_aster(self):
        reply = self.store.add_lyra_reply(1, "我有看到，我在这里。")
        leased = self.store.lease_pending()
        self.assertEqual([x.id for x in leased], [reply["id"]])
        self.store.add_aster_response(1, "信号收到了。", in_reply_to=reply["id"])
        self.assertEqual(self.store.ack_delivery([reply["id"]], leased[0].lease_token), 1)
        self.assertTrue(self.store.verify()["ok"])

    def test_release_on_failure_path(self):
        reply = self.store.add_lyra_reply(1, "不要丢失。")
        leased = self.store.lease_pending()
        self.assertEqual(self.store.release_lease([reply["id"]], leased[0].lease_token), 1)
        self.assertEqual(self.store.lease_pending()[0].id, reply["id"])


if __name__ == "__main__":
    unittest.main()
