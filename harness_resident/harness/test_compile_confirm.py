#!/usr/bin/env python3
"""TEST: register+confirm binds full candidate; rejects elevate and foreign owner."""
from __future__ import annotations
import sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import compile_confirm as CC


class ConfirmTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        CC.DB = Path(self.td.name) / "c.sqlite"

    def tearDown(self):
        self.td.cleanup()

    def test_register_confirm_idempotent(self):
        jobs = []
        def create_job(**kw):
            jobs.append(kw)
            return {"job_id": "J-test1", "status": "queued"}
        goal = "build hello " + str(time.time())
        reg = CC.register(owner="alice", session_id="s1", goal=goal)
        self.assertTrue(reg["ok"])
        a = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"]},
            create_job=create_job, owner="alice",
        )
        b = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"]},
            create_job=create_job, owner="alice",
        )
        self.assertTrue(a["ok"])
        self.assertFalse(a.get("idempotent"))
        self.assertTrue(b.get("idempotent"))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["origin"], "grid_c_confirm")
        self.assertEqual(jobs[0]["context_hash"], reg["binding_hash"])

    def test_three_counts_job_claim_side_effect(self):
        """T04: job rows, claim/executor events, and create_job side effects are separate."""
        from db import Store
        store = Store(str(Path(self.td.name) / "counts.db"))
        side = {"n": 0}

        def create_job(**kw):
            side["n"] += 1
            return store.create_job(
                channel="grid", goal=kw.get("goal") or "g", worker="cc",
                allowed_tools=["Read"], allowed_paths=[], cloud_allowed=False,
                approval_mode="auto", origin="grid_c_confirm",
                context_hash=kw.get("context_hash") or "",
            )

        reg = CC.register(owner="alice", session_id="s1", goal="three-count")
        a = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"]},
            create_job=create_job, owner="alice",
        )
        b = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"]},
            create_job=create_job, owner="alice",
        )
        self.assertTrue(a["ok"])
        self.assertTrue(b.get("idempotent"))
        rows = store.list_jobs(limit=20)
        confirm = [j for j in rows if j.get("origin") == "grid_c_confirm"]
        self.assertEqual(len(confirm), 1)
        claimed = store.claim_next_queued()
        self.assertEqual(claimed["job_id"], confirm[0]["job_id"])
        events = store.list_events(claimed["job_id"])
        self.assertTrue(any(e["kind"] == "job_claimed" for e in events))
        self.assertEqual(side["n"], 1)
        self.assertEqual(sum(1 for e in events if e["kind"] == "job_claimed"), 1)

    def test_same_goal_new_candidate_new_job(self):
        jobs = []
        n = {"i": 0}
        def create_job(**kw):
            n["i"] += 1
            jobs.append(kw)
            return {"job_id": f"J-{n['i']}", "status": "queued"}
        goal = "same goal"
        a = CC.register(owner="alice", session_id="s1", goal=goal)
        b = CC.register(owner="alice", session_id="s1", goal=goal)
        CC.submit({"candidate_id": a["candidate_id"], "binding_hash": a["binding_hash"]},
                  create_job=create_job, owner="alice")
        CC.submit({"candidate_id": b["candidate_id"], "binding_hash": b["binding_hash"]},
                  create_job=create_job, owner="alice")
        self.assertEqual(len(jobs), 2)

    def test_crash_after_reserve_recovers_one_job(self):
        jobs = []
        def create_job(**kw):
            jobs.append(kw)
            return {"job_id": "J-recovered", "status": "queued"}
        reg = CC.register(owner="alice", session_id="s1", goal="crash-window")
        import sqlite3
        con = sqlite3.connect(str(CC.DB))
        con.execute("UPDATE candidates SET job_id=? WHERE candidate_id=?",
                    ("reserved:" + reg["candidate_id"], reg["candidate_id"]))
        con.commit(); con.close()
        a = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"]},
            create_job=create_job, owner="alice",
        )
        b = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"]},
            create_job=create_job, owner="alice",
        )
        self.assertTrue(a["ok"])
        self.assertEqual(a["job_id"], "J-recovered")
        self.assertTrue(b.get("idempotent"))
        self.assertEqual(len(jobs), 1)

    def test_foreign_owner(self):
        reg = CC.register(owner="alice", session_id="s1", goal="x")
        out = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"]},
            create_job=lambda **k: {}, owner="bob",
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "unknown_or_foreign_candidate")

    def test_modified_binding(self):
        reg = CC.register(owner="alice", session_id="s1", goal="x")
        out = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": "0" * 64},
            create_job=lambda **k: {}, owner="alice",
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "modified_candidate")

    def test_client_cannot_elevate(self):
        reg = CC.register(owner="alice", session_id="s1", goal="x")
        out = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"],
             "worker": "research", "approval_mode": "god"},
            create_job=lambda **k: {}, owner="alice",
        )
        self.assertFalse(out["ok"])

    def test_expired_candidate(self):
        import json, sqlite3
        reg = CC.register(owner="alice", session_id="s1", goal="expire me")
        con = sqlite3.connect(str(CC.DB))
        con.row_factory = sqlite3.Row
        row = dict(con.execute("SELECT * FROM candidates WHERE candidate_id=?", (reg["candidate_id"],)).fetchone())
        rec = {
            "candidate_id": row["candidate_id"], "owner": row["owner"],
            "session_id": row["session_id"], "goal": row["goal"],
            "worker": row["worker"],
            "allowed_tools": json.loads(row["allowed_tools"]),
            "allowed_paths": json.loads(row["allowed_paths"]),
            "workdir": row["workdir"], "budget_ms": row["budget_ms"],
            "expires_at": time.time() - 5, "version": row["version"],
        }
        rec["binding_hash"] = CC.binding_hash(rec)
        con.execute("UPDATE candidates SET expires_at=?, binding_hash=? WHERE candidate_id=?",
                    (rec["expires_at"], rec["binding_hash"], rec["candidate_id"]))
        con.commit(); con.close()
        out = CC.submit(
            {"candidate_id": rec["candidate_id"], "binding_hash": rec["binding_hash"]},
            create_job=lambda **k: {"job_id": "nope"}, owner="alice",
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "expired_candidate")

    def test_confirmed_replay_after_expiry(self):
        jobs = []
        def create_job(**kw):
            jobs.append(kw)
            return {"job_id": "J-kept", "status": "queued"}
        reg = CC.register(owner="alice", session_id="s1", goal="keep")
        a = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"]},
            create_job=create_job, owner="alice",
        )
        self.assertTrue(a["ok"])
        import json, sqlite3
        con = sqlite3.connect(str(CC.DB))
        con.execute("UPDATE candidates SET expires_at=? WHERE candidate_id=?",
                    (time.time() - 5, reg["candidate_id"]))
        con.commit(); con.close()
        b = CC.submit(
            {"candidate_id": reg["candidate_id"], "binding_hash": reg["binding_hash"]},
            create_job=create_job, owner="alice",
        )
        self.assertTrue(b["ok"])
        self.assertTrue(b.get("idempotent"))
        self.assertEqual(b["job_id"], "J-kept")
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
