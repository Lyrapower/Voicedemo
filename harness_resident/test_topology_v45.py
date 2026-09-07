#!/usr/bin/env python3
"""GRID_TOPOLOGY v4.5 isolated tests. No production store / diary / 8501 writes."""
from __future__ import annotations
import os, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.chdir(HERE)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

os.environ.setdefault("HARNESS_PROVENANCE_LOG", "")


class OpsTests(unittest.TestCase):
    def test_fs_stat(self):
        from harness.ops import classify_steps
        c = classify_steps([{"op": "FS_STAT", "target": "harness_resident/harness"}])
        self.assertIsNone(c["worker"])
        self.assertEqual(c["executor"], "tool")
        self.assertTrue(c["read_only"])
        self.assertFalse(c["blocked"])

    def test_topology_sync(self):
        from harness.ops import classify_steps
        c = classify_steps([{"op": "TOPOLOGY_SYNC"}])
        self.assertTrue(c["topology_ack"])
        self.assertEqual(c["kind"], "ack")
        self.assertFalse(c["blocked"])

    def test_mixed_ack_and_fs(self):
        from harness.ops import classify_steps
        c = classify_steps([{"op": "TOPOLOGY_SYNC"}, {"op": "FS_STAT"}])
        self.assertIsNone(c["worker"])
        self.assertTrue(c["read_only"])
        self.assertTrue(c["topology_ack"])
        self.assertEqual(c["executor"], "tool")
        self.assertFalse(c["blocked"])

    def test_fs_write_blocked(self):
        from harness.ops import classify_steps
        c = classify_steps([{"op": "FS_WRITE"}])
        self.assertTrue(c["blocked"])
        self.assertFalse(c["read_only"])


class TopologyHelperTests(unittest.TestCase):
    def test_clamp_upper(self):
        from harness.topology import clamp_latency_ms
        self.assertEqual(clamp_latency_ms(999999, cap_ms=5000), 5000)

    def test_clamp_one(self):
        from harness.topology import clamp_latency_ms
        self.assertEqual(clamp_latency_ms(1, cap_ms=120000), 1)

    def test_scope_empty_is_full(self):
        from harness.topology import resolve_scope
        os.environ.pop("GRID_HARNESS_TOKEN", None)
        os.environ.pop("GRID_HARNESS_H1_TOKEN", None)
        os.environ.pop("GRID_HARNESS_PAGE_TOKEN", None)
        self.assertEqual(resolve_scope(""), "full")

    def test_scope_h1(self):
        from harness.topology import resolve_scope
        os.environ["GRID_HARNESS_H1_TOKEN"] = "h1-test"
        os.environ["GRID_HARNESS_PAGE_TOKEN"] = "page-test"
        os.environ["GRID_HARNESS_TOKEN"] = "full-test"
        try:
            self.assertEqual(resolve_scope("h1-test"), "h1")
            self.assertEqual(resolve_scope("page-test"), "page")
            self.assertEqual(resolve_scope("full-test"), "full")
            self.assertIsNone(resolve_scope("nope"))
        finally:
            for k in ("GRID_HARNESS_H1_TOKEN", "GRID_HARNESS_PAGE_TOKEN", "GRID_HARNESS_TOKEN"):
                os.environ.pop(k, None)


class DbAndCreateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "t.db"
        self.prov = Path(self.tmp.name) / "p.jsonl"
        os.environ["HARNESS_PROVENANCE_LOG"] = str(self.prov)
        from harness.db import Store
        self.store = Store(str(self.db))
        import harness.api as api
        self.api = api
        self._old = api.store
        api.store = self.store

    def tearDown(self):
        self.api.store = self._old
        os.environ.pop("HARNESS_PROVENANCE_LOG", None)
        self.tmp.cleanup()

    def test_no_hash_400(self):
        from fastapi import HTTPException
        body = self.api.JobCreate(goal="x", origin="grid_compiled", context_hash="", steps=[{"op": "FS_STAT"}])
        with self.assertRaises(HTTPException) as ctx:
            self.api.create_job_internal(body)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_ack_done(self):
        body = self.api.JobCreate(
            goal="block", origin="grid_compiled", context_hash="abc",
            steps=[{"op": "TOPOLOGY_SYNC"}],
        )
        job = self.api.create_job_internal(body)
        self.assertEqual(job["status"], "done")
        self.assertTrue(job["topology_ack"])
        self.assertEqual(job["context_hash"], "abc")
        self.assertEqual(job["origin"], "grid_compiled")
        rec = self.store.get_job_receipt_by_job(job["job_id"])
        self.assertIsNotNone(rec)
        got = self.api.api_get_receipt.__wrapped__ if hasattr(self.api.api_get_receipt, "__wrapped__") else None
        # direct store check + receipt helper
        from harness.topology import provenance_line_raw
        line = provenance_line_raw(job.get("receipt_event_id") or "")
        self.assertTrue(line or rec["receipt_line"])

    def test_fs_tool_bytes_match_stat(self):
        import json as jsonlib
        from harness.ops import DEMO_ROOT
        target = DEMO_ROOT / "harness_resident" / "harness"
        body = self.api.JobCreate(
            goal="block", origin="grid_compiled", context_hash="def",
            steps=[{"op": "FS_STAT", "target": "harness_resident/harness"}],
        )
        job = self.api.create_job_internal(body)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["last_step"], "fs_tool")
        self.assertTrue(job["read_only"])
        rec = self.store.get_job_receipt_by_job(job["job_id"])
        self.assertIsNotNone(rec)
        data = jsonlib.loads(rec["worker_output"])
        files = [p for p in target.iterdir() if p.is_file() and not p.name.startswith(".")]
        biggest = max(files, key=lambda p: p.stat().st_size)
        self.assertEqual(data["executor"], "tool")
        self.assertEqual(data["fs_data"]["file_count"], len(files))
        self.assertEqual(data["fs_data"]["max_file"]["name"], biggest.name)
        self.assertEqual(data["fs_data"]["max_file"]["size_bytes"], int(biggest.stat().st_size))
        self.assertEqual(data["fs_data"]["max_file"]["size_bytes"], os.stat(biggest).st_size)
        stream = [e for e in self.store.list_stream_events(after_seq=0)
                  if e.get("job_id") == job["job_id"] and e.get("kind") == "receipt"]
        self.assertTrue(stream)
        line = stream[-1]["payload"].get("receipt_line") or ""
        self.assertTrue(line.strip())
        self.assertIn(job.get("receipt_event_id") or "", line)

    def test_write_blocked_full(self):
        body = self.api.JobCreate(
            goal="block", origin="grid_compiled", context_hash="ghi",
            steps=[{"op": "FS_WRITE"}],
        )
        job = self.api.create_job_internal(body, scope="full")
        self.assertEqual(job["status"], "blocked")

    def test_write_403_h1(self):
        from fastapi import HTTPException
        body = self.api.JobCreate(
            goal="block", origin="grid_compiled", context_hash="jkl",
            steps=[{"op": "FS_WRITE"}],
        )
        with self.assertRaises(HTTPException) as ctx:
            self.api.create_job_internal(body, scope="h1")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(len(self.store.list_jobs(100)), 0)

    def test_parse_action_plan_target(self):
        from harness.ops import parse_action_plan
        steps = parse_action_plan(
            "action_plan:\n    - op: FS_STAT\n      target: harness_resident/harness\n      scope: [file_count, max_file]\n"
        )
        self.assertEqual(steps[0]["op"], "FS_STAT")
        self.assertEqual(steps[0]["target"], "harness_resident/harness")

    def test_ignore_extra_on_model(self):
        body = self.api.ApiJobBody(content="x", extra_unknown="nope")  # type: ignore[call-arg]
        self.assertEqual(body.content, "x")
        self.assertFalse(hasattr(body, "extra_unknown"))


if __name__ == "__main__":
    unittest.main()
