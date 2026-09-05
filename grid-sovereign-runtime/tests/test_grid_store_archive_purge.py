"""epoch purge must MOVE production chat into messages_archive (never hard-delete)."""
from __future__ import annotations

import os
import tempfile
import time
import unittest

from gateway.grid_store import ARCHIVE_ON_PURGE_NODES, GridStore, WORKBENCH_B11_NODE


class ArchivePurgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.store = GridStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_workbench_b11_purge_moves_not_destroys(self):
        self.assertIn(WORKBENCH_B11_NODE, ARCHIVE_ON_PURGE_NODES)
        # before_ts must be ≤ current epoch start (RED LINE); use epoch boundary
        import datetime as dt

        anchor = dt.date(2026, 7, 16)
        today = dt.date.today()
        idx = (today - anchor).days // 7
        epoch = dt.datetime.combine(anchor + dt.timedelta(days=idx * 7), dt.time.min).timestamp()
        old = epoch - 100
        self.store.append_messages(
            WORKBENCH_B11_NODE,
            [
                {"role": "user", "content": "hello-old", "ts": old},
                {"role": "assistant", "content": "hi-old", "ts": old + 1},
            ],
        )
        moved = self.store.purge_messages_before(WORKBENCH_B11_NODE, epoch)
        self.assertEqual(moved, 2)
        self.assertEqual(self.store.get_messages(WORKBENCH_B11_NODE, limit=50), [])
        arch = self.store.get_archived_messages(WORKBENCH_B11_NODE, limit=50)
        self.assertEqual(len(arch), 2)
        self.assertEqual(arch[0]["content"], "hello-old")
        self.assertEqual(self.store.archive_count(WORKBENCH_B11_NODE), 2)

    def test_smoke_node_still_hard_deletes(self):
        old = time.time() - 1000
        self.store.append_messages(
            "smoke_node",
            [{"role": "user", "content": "ping", "ts": old}],
        )
        n = self.store.purge_messages_before("smoke_node", time.time())
        self.assertEqual(n, 1)
        self.assertEqual(self.store.archive_count("smoke_node"), 0)


if __name__ == "__main__":
    unittest.main()
