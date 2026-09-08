#!/usr/bin/env python3
"""Isolated scheduler ticks. Does not write production task_schedule.json."""
from __future__ import annotations
import json, tempfile, time, unittest
from pathlib import Path
import task_schedule as TS


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.state = Path(self.td.name) / "sched.json"
        self.reg = Path(__file__).resolve().parents[1] / "tasks" / "registry.json"
        self.jobs = []

    def tearDown(self):
        self.td.cleanup()

    def _create(self, **kw):
        jid = f"J-iso-{len(self.jobs)+1}"
        self.jobs.append(kw)
        return {"job_id": jid, "status": "queued"}

    def test_due_now_enqueues_once(self):
        now = time.time()
        self.state.write_text(json.dumps({
            "enabled": True,
            "tasks": {"opportunity-scout": {
                "enabled": True, "next_due_ts": now - 10,
                "next_due_at": None, "last_job_id": None,
            }},
        }))
        a = TS.enqueue_due(create_job=self._create, now=now, state_path=self.state, registry_path=self.reg)
        b = TS.enqueue_due(create_job=self._create, now=now + 1, state_path=self.state, registry_path=self.reg)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["task_id"], "opportunity-scout")
        self.assertEqual(b, [])
        self.assertEqual(len(self.jobs), 1)

    def test_disable_no_enqueue(self):
        now = time.time()
        self.state.write_text(json.dumps({
            "enabled": True,
            "tasks": {"opportunity-scout": {"enabled": False, "next_due_ts": now - 10}},
        }))
        out = TS.enqueue_due(create_job=self._create, now=now, state_path=self.state, registry_path=self.reg)
        self.assertEqual(out, [])

    def test_coalesce_missed(self):
        now = time.time()
        self.state.write_text(json.dumps({
            "enabled": True,
            "tasks": {"opportunity-scout": {"enabled": True, "next_due_ts": now - 90000}},
        }))
        out = TS.enqueue_due(create_job=self._create, now=now, state_path=self.state, registry_path=self.reg)
        self.assertEqual(len(out), 1)
        st = json.loads(self.state.read_text())
        self.assertGreater(st["tasks"]["opportunity-scout"]["next_due_ts"], now)

    def test_first_sight_does_not_fire(self):
        now = time.time()
        self.state.write_text(json.dumps({"enabled": True, "tasks": {}}))
        out = TS.enqueue_due(create_job=self._create, now=now, state_path=self.state, registry_path=self.reg)
        self.assertEqual(out, [])
        self.assertEqual(self.jobs, [])
        st = json.loads(self.state.read_text())
        for tid in ("autonomous-builder", "knowledge-gardener", "opportunity-scout", "rwa-infrastructure"):
            self.assertTrue(st["tasks"][tid]["enabled"])
            self.assertGreater(st["tasks"][tid]["next_due_ts"], now)

    def test_same_due_key_enqueues_once(self):
        now = time.time()
        due = now - 10
        self.state.write_text(json.dumps({
            "enabled": True,
            "tasks": {"opportunity-scout": {
                "enabled": True, "next_due_ts": due,
            }},
        }))
        a = TS.enqueue_due(create_job=self._create, now=now, state_path=self.state, registry_path=self.reg,
                           origin="isolated_sched")
        st = json.loads(self.state.read_text())
        st["tasks"]["opportunity-scout"]["next_due_ts"] = due
        self.state.write_text(json.dumps(st))
        b = TS.enqueue_due(create_job=self._create, now=now, state_path=self.state, registry_path=self.reg,
                           origin="isolated_sched")
        self.assertEqual(len(a), 1)
        self.assertEqual(b, [])
        self.assertEqual(self.jobs[0]["origin"], "isolated_sched")

    def test_dual_scheduler_same_due_one_job(self):
        import threading
        now = time.time()
        due = now - 10
        self.state.write_text(json.dumps({
            "enabled": True,
            "tasks": {"opportunity-scout": {"enabled": True, "next_due_ts": due}},
        }))
        barrier = threading.Barrier(2)
        def run():
            barrier.wait()
            TS.enqueue_due(create_job=self._create, now=now, state_path=self.state, registry_path=self.reg,
                           origin="isolated_sched")
        t1 = threading.Thread(target=run); t2 = threading.Thread(target=run)
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(len(self.jobs), 1)

    def test_disable_does_not_cancel_existing_jobs(self):
        """disable stops future enqueue only; it does not cancel already created jobs."""
        now = time.time()
        self.state.write_text(json.dumps({
            "enabled": True,
            "tasks": {"opportunity-scout": {"enabled": True, "next_due_ts": now - 10}},
        }))
        out = TS.enqueue_due(create_job=self._create, now=now, state_path=self.state, registry_path=self.reg)
        self.assertEqual(len(out), 1)
        st = json.loads(self.state.read_text())
        st["tasks"]["opportunity-scout"]["enabled"] = False
        self.state.write_text(json.dumps(st))
        later = TS.enqueue_due(create_job=self._create, now=now + 1, state_path=self.state, registry_path=self.reg)
        self.assertEqual(later, [])
        self.assertEqual(len(self.jobs), 1)

    def test_isolated_origin_skipped_by_production_claim(self):
        from db import Store
        prod = Store(str(Path(self.td.name) / "prod.db"))
        iso = Store(str(Path(self.td.name) / "iso.db"))
        leaked = prod.create_job(
            channel="autonomous", goal="iso leak", worker="research",
            allowed_tools=["Read"], allowed_paths=[], cloud_allowed=True,
            approval_mode="write_ok_no_deploy", origin="isolated_sched",
        )
        real = prod.create_job(
            channel="autonomous", goal="prod job", worker="research",
            allowed_tools=["Read"], allowed_paths=[], cloud_allowed=True,
            approval_mode="write_ok_no_deploy", origin="",
        )
        claimed = prod.claim_next_queued()
        self.assertEqual(claimed["job_id"], real["job_id"])
        self.assertIsNone(prod.claim_next_queued())
        still = prod.get_job(leaked["job_id"])
        self.assertEqual(still["status"], "queued")
        iso_job = iso.create_job(
            channel="autonomous", goal="iso own", worker="research",
            allowed_tools=["Read"], allowed_paths=[], cloud_allowed=True,
            approval_mode="write_ok_no_deploy", origin="isolated_sched",
        )
        got = iso.claim_next_queued(isolated=True)
        self.assertEqual(got["job_id"], iso_job["job_id"])
        self.assertIsNone(iso.claim_next_queued())
        events = prod.list_events(real["job_id"])
        self.assertTrue(any(e["kind"]=="job_claimed" for e in events))

    def test_confirm_hash_unique_and_cc_interrupt_not_requeued(self):
        from db import Store
        s = Store(str(Path(self.td.name) / "uniq.db"))
        a = s.create_job(
            channel="grid", goal="g", worker="cc", allowed_tools=["Read"], allowed_paths=[],
            cloud_allowed=False, approval_mode="auto", origin="grid_c_confirm",
            context_hash="abc"*8+"def",
        )
        b = s.create_job(
            channel="grid", goal="g2", worker="cc", allowed_tools=["Read"], allowed_paths=[],
            cloud_allowed=False, approval_mode="auto", origin="grid_c_confirm",
            context_hash="abc"*8+"def",
        )
        self.assertEqual(a["job_id"], b["job_id"])
        s.update_job(a["job_id"], status="running")
        n = s.mark_running_interrupted()
        self.assertEqual(n, 1)
        q = s.requeue_interrupted(3)
        self.assertEqual(q, 0)
        self.assertEqual(s.get_job(a["job_id"])["status"], "blocked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
