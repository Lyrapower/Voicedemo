import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import chat_memory


class ChatMemoryEpochTests(unittest.TestCase):
    def test_epoch_anchor_first_week(self):
        start = chat_memory.current_epoch_start(today=dt.date(2026, 7, 16))
        self.assertEqual(start, dt.date(2026, 7, 16))

    def test_epoch_rolls_on_day_eight(self):
        start = chat_memory.current_epoch_start(today=dt.date(2026, 7, 23))
        self.assertEqual(start, dt.date(2026, 7, 23))

    def test_build_messages_soul_only_no_history_arg(self):
        # 无 history 参数;末条为当前 user(前缀可能为空若无 DB)
        out = chat_memory.build_gateway_messages(
            {"continue": False}, "新一句", continue_user="go",
        )
        self.assertEqual(out[-1], {"role": "user", "content": "新一句"})
        self.assertTrue(all(m.get("role") in ("system", "user") for m in out[:-1]) or len(out) == 1)

    def test_build_continue_no_store_history(self):
        body = {"continue": True, "prior_text": "partial", "original_message": "写json"}
        out = chat_memory.build_gateway_messages(body, "", continue_user="continue")
        self.assertEqual(out[-1]["content"], "continue")
        self.assertEqual(out[-2], {"role": "assistant", "content": "partial"})
        self.assertEqual(out[-3], {"role": "user", "content": "写json"})

    def test_compile_lane_node(self):
        self.assertEqual(chat_memory.node_for_task("compile_json"), chat_memory.NODE_COMPILE)


class GridStoreMemoryTests(unittest.TestCase):
    def test_since_ts_and_purge(self):
        gw = Path(__file__).resolve().parents[2] / "grid-sovereign-runtime" / "gateway"
        sys.path.insert(0, str(gw))
        from grid_store import GridStore

        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "t.db")
            store = GridStore(db)
            old_ts = dt.datetime(2026, 7, 10).timestamp()
            new_ts = dt.datetime(2026, 7, 16, 12).timestamp()
            store.append_messages("field-particle", [
                {"role": "user", "content": "old", "ts": old_ts},
                {"role": "assistant", "content": "old-reply", "ts": old_ts + 1},
            ])
            store.append_messages("field-particle", [
                {"role": "user", "content": "new", "ts": new_ts},
            ])
            epoch_ts = dt.datetime(2026, 7, 16).timestamp()
            recent = store.get_messages("field-particle", limit=50, since_ts=epoch_ts)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["content"], "new")
            deleted = store.purge_messages_before("field-particle", epoch_ts)
            self.assertEqual(deleted, 2)
            self.assertEqual(len(store.get_messages("field-particle", limit=50)), 1)


if __name__ == "__main__":
    unittest.main()
