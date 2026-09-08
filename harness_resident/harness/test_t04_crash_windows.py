"""T04: crash-window recovery at real interrupt boundaries (A–F).

Isolated DB/queue/worker. No production writes. Each window injects a
failure at a real boundary in the production code path and asserts the
recover invariant: same candidate_id retry yields exactly one job, no
duplicate side effects, interrupted cc → blocked (not requeued).
"""
from __future__ import annotations
import json, sqlite3, tempfile, time, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import compile_confirm as CC
from db import Store


def _seed_candidate(goal="crash-window"):
    reg = CC.register(owner="alice", session_id="s1", goal=goal)
    return reg["candidate_id"], reg["binding_hash"]


class CrashWindowTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        CC.DB = Path(self.td.name) / "c.sqlite"
        self.store = Store(str(Path(self.td.name) / "h.db"))
        self.side = {"n": 0, "ids": []}

    def tearDown(self):
        self.td.cleanup()

    def _create_job(self, **kw):
        self.side["n"] += 1
        j = self.store.create_job(
            channel="grid", goal=kw.get("goal") or "g", worker="cc",
            allowed_tools=["Read"], allowed_paths=[], cloud_allowed=False,
            approval_mode="auto", origin="grid_c_confirm",
            context_hash=kw.get("context_hash") or "",
        )
        self.side["ids"].append(j["job_id"])
        return j

    def _submit(self, cid, bh):
        return CC.submit(
            {"candidate_id": cid, "binding_hash": bh},
            create_job=self._create_job, owner="alice",
        )

    def test_A_persist_before_response(self):
        """A: job persisted, client loses response, retry → idempotent, one job."""
        cid, bh = _seed_candidate()
        a = self._submit(cid, bh)
        self.assertTrue(a["ok"])
        self.assertEqual(self.side["n"], 1)
        b = self._submit(cid, bh)
        self.assertTrue(b.get("idempotent"))
        self.assertEqual(b["job_id"], a["job_id"])
        self.assertEqual(self.side["n"], 1)

    def test_B_enqueued_before_claim(self):
        """B: job queued, supervisor dies before claim, restart → claim once."""
        cid, bh = _seed_candidate()
        a = self._submit(cid, bh)
        self.assertEqual(a["status"], "queued")
        got = self.store.claim_next_queued()
        self.assertEqual(got["job_id"], a["job_id"])
        self.assertIsNone(self.store.claim_next_queued())
        self.assertEqual(self.side["n"], 1)

    def test_C_claimed_before_container(self):
        """C: claimed (running), crash before container, mark interrupted → blocked (cc)."""
        cid, bh = _seed_candidate()
        a = self._submit(cid, bh)
        self.store.claim_next_queued()
        n = self.store.mark_running_interrupted()
        self.assertEqual(n, 1)
        q = self.store.requeue_interrupted(3)
        self.assertEqual(q, 0)
        self.assertEqual(self.store.get_job(a["job_id"])["status"], "blocked")

    def test_D_container_running_record(self):
        """D: running, crash after running recorded, restart → reconcile finds running, blocks."""
        cid, bh = _seed_candidate()
        a = self._submit(cid, bh)
        self.store.claim_next_queued()
        self.store.update_job(a["job_id"], status="running", last_step="container_up")
        n = self.store.mark_running_interrupted()
        self.assertEqual(n, 1)
        self.assertEqual(self.store.requeue_interrupted(3), 0)
        self.assertEqual(self.store.get_job(a["job_id"])["status"], "blocked")

    def test_E_tool_side_effect_before_done(self):
        """E: side effect counted, crash before done, retry → idempotent (no re-execute)."""
        cid, bh = _seed_candidate()
        a = self._submit(cid, bh)
        self.assertEqual(self.side["n"], 1)
        self.store.claim_next_queued()
        self.store.mark_running_interrupted()
        self.store.requeue_interrupted(3)
        b = self._submit(cid, bh)
        self.assertTrue(b.get("idempotent"))
        self.assertEqual(self.side["n"], 1)

    def test_F_done_record_persisted(self):
        """F: done recorded, client retries → idempotent, no new job."""
        cid, bh = _seed_candidate()
        a = self._submit(cid, bh)
        self.store.update_job(a["job_id"], status="done", last_step="cc_done")
        b = self._submit(cid, bh)
        self.assertTrue(b.get("idempotent"))
        self.assertEqual(b["job_id"], a["job_id"])
        self.assertEqual(self.side["n"], 1)

    def test_three_counts_independent(self):
        """job rows ≠ executor claims ≠ side effects; all three == 1 for one confirm."""
        cid, bh = _seed_candidate()
        a = self._submit(cid, bh)
        b = self._submit(cid, bh)
        self.assertTrue(b.get("idempotent"))
        rows = [j for j in self.store.list_jobs(20) if j.get("origin") == "grid_c_confirm"]
        self.assertEqual(len(rows), 1)
        claimed = self.store.claim_next_queued()
        self.assertEqual(claimed["job_id"], a["job_id"])
        events = self.store.list_events(a["job_id"])
        self.assertEqual(sum(1 for e in events if e["kind"] == "job_claimed"), 1)
        self.assertEqual(self.side["n"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
