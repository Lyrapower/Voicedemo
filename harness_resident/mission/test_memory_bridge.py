"""BRIDGE offline: Astra idempotency, shared-only write, SIGNAL_RE, dest lock."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.db import Store
from harness.memory_bridge import (
    MemoryBridge, SHARED_NODE, SELFTEST_NODE, project_work_card, signal_blocked,
    PROJECTION_VERSION,
)


class TestMemoryBridge(unittest.TestCase):
    def test_signal_blocks_card(self):
        self.assertTrue(signal_blocked("买入 AAPL 目标价: $12"))
        self.assertIsNone(project_work_card({
            "receipt_id": "E1", "mid": "M-1", "result": "买入 TSLA 目标价: $1",
        }))

    def test_research_tag(self):
        line = project_work_card({
            "receipt_id": "E2", "mid": "M-1", "worker": "research", "result": "ok",
        })
        self.assertIsNotNone(line)
        self.assertIn("worker_role=research", line)
        self.assertIn("producer_model_id=unknown", line)
        self.assertIn("producer_family=unknown", line)
        self.assertNotIn("deepseek_inbound", line)
        self.assertNotIn("DeepSeek", line)

    def test_idempotent_receipt_id(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td) / "t.db"))
            br = MemoryBridge(store, dest=SELFTEST_NODE)
            rec = {"receipt_id": "R-same", "mid": "M-x", "worker": "deep",
                   "lane": "scout", "result": "hop ok", "ts": 1}
            with patch("harness.memory_bridge._append_shared", return_value=(True, "")):
                a = br.offer(rec)
                b = br.offer(rec)
            self.assertEqual(a["status"], "delivered")
            self.assertEqual(b["status"], "idempotent")
            row = store.get_bridge_outbox("R-same", SELFTEST_NODE, PROJECTION_VERSION)
            self.assertEqual(row["status"], "delivered")

    def test_dest_must_be_shared(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td) / "t.db"))
            with self.assertRaises(ValueError):
                MemoryBridge(store, dest="deep")
            with self.assertRaises(ValueError):
                MemoryBridge(store, dest="cloud-deepseek")

    def test_shared_constant(self):
        self.assertEqual(SHARED_NODE, "harness-shared")

    def test_model_from_receipt_not_role(self):
        line = project_work_card({
            "receipt_id": "E3", "mid": "M-glm", "worker": "deep",
            "producer_model_id": "glm-5.2:cloud", "producer_family": "glm",
            "producer_run_id": "run-1", "result": "ok", "ts": 1789000000,
        })
        self.assertIn("worker_role=deep", line)
        self.assertIn("producer_model_id=glm-5.2:cloud", line)
        self.assertIn("producer_family=glm", line)
        self.assertIn("producer_run_id=run-1", line)
        self.assertNotIn("DeepSeek", line)

    def test_ambiguous_time_unknown(self):
        line = project_work_card({
            "receipt_id": "E4", "mid": "M-1", "worker": "deep",
            "occurred_at": "yesterday morning", "result": "ok",
        })
        self.assertIn("observed_at=unknown", line)

    def test_identity_forbids_role_to_model_guess(self):
        from harness.memory_bridge import identity_block
        block = identity_block()
        self.assertNotIn("research=DeepSeek", block)
        self.assertNotIn("deep=scout", block)
        self.assertIn("禁止从 worker_role 猜测", block)

    def test_mid_acl_isolates_ab(self):
        from harness.memory_bridge import load_shared_page
        cards = [
            "[工作日志] mission_id=M-A job_id=J-1 worker_role=deep producer_family=glm "
            "producer_model_id=glm-5.2:cloud source_receipt_id=R-A result=ok",
            "[工作日志] mission_id=M-B job_id=J-2 worker_role=research producer_family=deepseek "
            "producer_model_id=deepseek-v4-pro:cloud source_receipt_id=R-B result=ok",
        ]
        with patch("harness.store_memory.get_messages", return_value=[{"content": c} for c in cards]):
            a = load_shared_page(allowed_mids=["M-A"])
            b = load_shared_page(allowed_mids=["M-B"])
        self.assertEqual(len(a["cards"]), 1)
        self.assertIn("mission_id=M-A", a["cards"][0])
        self.assertNotIn("M-B", a["cards"][0])
        self.assertEqual(len(b["cards"]), 1)
        self.assertIn("mission_id=M-B", b["cards"][0])

    def test_no_pin_mids(self):
        from harness import memory_bridge as mb
        self.assertFalse(hasattr(mb, "PIN_MIDS"))
        self.assertFalse(hasattr(mb, "prioritize_cards"))


if __name__ == "__main__":
    unittest.main()
