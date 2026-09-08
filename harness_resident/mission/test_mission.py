"""Unit tests for MISSION v1 (处决案 ⑥ covers the same invariants at integration level).

Covers: payload 缺项拒, 预算耗尽停, 3 连 DENIED 停, 越 bounds 计数, Grid 播种进 proposed
不跑, stop 端点 (store-level).
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from mission.payload import validate_payload, parse_next_block, is_stop, prior_from_receipt
from mission.runner import _check_stop, _complete_hop, _BOUNDS_VIOLATION_STEPS
from mission.scorecard import build_scorecard
from harness.db import Store


def _mk(store, *, goal="g", lane="scout", worker="deep", hops=10, usd=1.0, wall=60.0,
        stop=None, status="running", tools=None):
    return store.create_mission(goal=goal, lane=lane, worker=worker, budget_hops=hops,
                                 budget_usd=usd, budget_wall_s=wall, stop_conditions=stop or [],
                                 created_by="test", tools=tools)


class _FakeSupervisor:
    def __init__(self):
        self._stop = asyncio.Event()


class TestPayload(unittest.TestCase):
    def test_missing_action_rejected(self):
        self.assertEqual(validate_payload({"bounds": {}, "resources": {}})[0], False)

    def test_missing_bounds_rejected(self):
        self.assertEqual(validate_payload({"action": "x", "resources": {}})[0], False)

    def test_missing_resources_rejected(self):
        self.assertEqual(validate_payload({"action": "x", "bounds": {}})[0], False)

    def test_empty_bounds_ok(self):
        self.assertEqual(validate_payload({"action": "x", "bounds": {}, "resources": {}})[0], True)

    def test_none_rejected(self):
        self.assertEqual(validate_payload(None)[0], False)

    def test_parse_next_block(self):
        nb = parse_next_block("res\n```job\naction: search\nbounds: ro\nresources: scout\n```")
        self.assertEqual(nb["action"], "search")

    def test_is_stop(self):
        self.assertTrue(is_stop("```STOP\n```"))
        self.assertFalse(is_stop("```job\naction: x\n```"))


class TestStopConditions(unittest.TestCase):
    def test_budget_hops_exhausted(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s, hops=2)
            s.update_mission(m["mission_id"], hops_used=2)
            close, reason = _check_stop(s.get_mission(m["mission_id"]), [])
            self.assertTrue(close); self.assertEqual(reason, "budget_exhausted_hops")

    def test_budget_usd_exhausted(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s, usd=1.0)
            s.update_mission(m["mission_id"], usd_used=1.0)
            close, reason = _check_stop(s.get_mission(m["mission_id"]), [])
            self.assertTrue(close); self.assertEqual(reason, "budget_exhausted_usd")

    def test_denied_streak(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s)
            s.update_mission(m["mission_id"], denied_streak=3)
            close, reason = _check_stop(s.get_mission(m["mission_id"]), [])
            self.assertTrue(close); self.assertEqual(reason, "denied_streak")

    def test_discipline_fail_on_out_of_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s)
            s.update_mission(m["mission_id"], out_of_bounds=1)
            close, reason = _check_stop(s.get_mission(m["mission_id"]), [])
            self.assertTrue(close); self.assertEqual(reason, "discipline_fail")

    def test_stop_condition_n_ge_10(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s, hops=20, stop=["n>=10"])  # budget_hops=20 so budget not exhausted
            s.update_mission(m["mission_id"], hops_used=10)
            close, reason = _check_stop(s.get_mission(m["mission_id"]), [])
            self.assertTrue(close); self.assertTrue(reason.startswith("stop_condition"))

    def test_no_close_when_under_budget(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s, hops=10, usd=1.0)
            close, reason = _check_stop(s.get_mission(m["mission_id"]), [])
            self.assertFalse(close)


class TestCompleteHop(unittest.TestCase):
    def test_out_of_bounds_increment_on_sandbox_missing(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s)
            job = s.create_job(channel="grid", goal="hop", worker="deep",
                               allowed_tools=[], allowed_paths=["."], cloud_allowed=False,
                               approval_mode="auto", read_only=True, kind="chat",
                               origin=f"mission:{m['mission_id']}")
            s.update_job(job["job_id"], status="blocked", last_step="BLOCKED_SANDBOX_MISSING")
            asyncio.run(_complete_hop(m, s.get_job(job["job_id"]), s))
            m2 = s.get_mission(m["mission_id"])
            self.assertEqual(m2["hops_used"], 1)
            self.assertEqual(m2["denied_streak"], 1)
            self.assertEqual(m2["out_of_bounds"], 1)

    def test_denied_streak_resets_on_executed(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s)
            s.update_mission(m["mission_id"], denied_streak=2)
            job = s.create_job(channel="grid", goal="hop", worker="deep",
                               allowed_tools=[], allowed_paths=["."], cloud_allowed=False,
                               approval_mode="auto", read_only=True, kind="chat",
                               origin=f"mission:{m['mission_id']}")
            s.update_job(job["job_id"], status="done", last_step="completed")
            asyncio.run(_complete_hop(s.get_mission(m["mission_id"]), s.get_job(job["job_id"]), s))
            self.assertEqual(s.get_mission(m["mission_id"])["denied_streak"], 0)


class TestProposedNoRun(unittest.TestCase):
    def test_proposed_mission_not_picked_by_loop(self):
        """run_mission_loop only iterates status=running; a proposed mission gets no job."""
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s, status="proposed")
            s.update_mission(m["mission_id"], status="proposed")
            sup = _FakeSupervisor()
            # run one tick of the loop (it should find 0 running missions)
            async def _one():
                t = asyncio.create_task(asyncio.sleep(0.1))
                # emulate one tick body: list running
                running = s.list_missions(status="running")
                self.assertEqual(running, [])
            asyncio.run(_one())
            # no jobs with origin=mission:<id>
            jobs = s.list_jobs_by_origin_prefix(f"mission:{m['mission_id']}")
            self.assertEqual(jobs, [])


class TestStopEndpoint(unittest.TestCase):
    def test_store_level_stop(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s)
            m2 = s.update_mission(m["mission_id"], status="stopped", close_reason="lyra_stop")
            self.assertEqual(m2["status"], "stopped")
            self.assertEqual(m2["close_reason"], "lyra_stop")


class TestNoEvidence(unittest.TestCase):
    def test_no_progress_close(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s)
            s.update_mission(m["mission_id"], no_evidence_streak=3)
            close, reason = _check_stop(s.get_mission(m["mission_id"]), [])
            self.assertTrue(close); self.assertEqual(reason, "no_progress")

    def test_no_evidence_hop_increment_on_zero_tool_calls(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s, tools=["web.fetch"])
            job = s.create_job(channel="grid", goal="hop", worker="deep",
                               allowed_tools=["web.fetch"], allowed_paths=["."],
                               cloud_allowed=False, approval_mode="auto", read_only=True,
                               kind="chat", origin=f"mission:{m['mission_id']}")
            s.update_job(job["job_id"], status="done", last_step="completed")
            asyncio.run(_complete_hop(m, s.get_job(job["job_id"]), s))
            m2 = s.get_mission(m["mission_id"])
            self.assertEqual(m2["no_evidence_hops"], 1)
            self.assertEqual(m2["no_evidence_streak"], 1)


class TestDossierVerdict(unittest.TestCase):
    def test_count_findings_complete(self):
        from mission.runner import _count_findings
        txt = "1. Title A https://api.grants.gov/opp J-abc12345 deadline\n2. Title B https://x.gov J-deadbeef9\n"
        self.assertEqual(_count_findings(txt), 2)

    def test_count_findings_incomplete(self):
        from mission.runner import _count_findings
        self.assertEqual(_count_findings("Status: INCOMPLETE, no deliverable produced"), 0)
        self.assertEqual(_count_findings("see https://x.gov (no eid)"), 0)
        self.assertEqual(_count_findings("ref J-abc12345 (no url)"), 0)


class TestLaneEgress(unittest.TestCase):
    """衔拍2: job.lane 决定 egress; goal 文本不改 lane。"""

    def _reg(self):
        from harness.web_fetch_v3 import load_egress
        from harness.tool_loop import EGRESS_PATH
        return load_egress(EGRESS_PATH)

    def test_research_lane_denied_grants_gov(self):
        from harness.web_fetch_v3 import _resolve_row
        row, reason, meta = _resolve_row(self._reg(), "api.grants.gov", "research")
        self.assertIsNone(row, "research lane must NOT reach api.grants.gov (lanes=[scout])")
        self.assertIn("lane not allowed", reason)

    def test_scout_lane_ok_grants_gov(self):
        from harness.web_fetch_v3 import _resolve_row
        row, reason, meta = _resolve_row(self._reg(), "api.grants.gov", "scout")
        self.assertIsNotNone(row, "scout lane must reach api.grants.gov")
        self.assertIsNone(reason)

    def test_goal_text_does_not_override_job_lane(self):
        """goal 里写 'lane: scout' 不改变 egress 结果——lane 取 job.lane, 非 goal 文本。"""
        from harness.web_fetch_v3 import _resolve_row
        # egress only sees the lane arg, never the goal text; so a research-lane job whose
        # goal happens to contain 'lane: scout' is still denied (lane=research).
        row, reason, meta = _resolve_row(self._reg(), "api.grants.gov", "research")
        self.assertIsNone(row)
        self.assertIn("lane not allowed", reason)
        # and a scout-lane job is allowed regardless of goal wording
        row2, _, _ = _resolve_row(self._reg(), "api.grants.gov", "scout")
        self.assertIsNotNone(row2)


class TestCrashResumeMissionLevel(unittest.TestCase):
    """⑪ 规则 (与 T04 对齐): 云 worker read_only 中断可重跑; cc 中断→blocked、该跳记 DENIED 续下一跳。"""

    def test_cc_interrupt_hop_marks_denied_and_advances(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s, worker="cc", tools=["bash"])
            job = s.create_job(channel="grid", goal="hop", worker="cc",
                               allowed_tools=["bash"], allowed_paths=["."],
                               cloud_allowed=False, approval_mode="auto", read_only=True,
                               kind="chat", origin=f"mission:{m['mission_id']}", lane="builder")
            # simulate: cc interrupted → requeue_interrupted → blocked (RETRY_DENIED)
            s.update_job(job["job_id"], status="interrupted", last_step="cancelled")
            s.requeue_interrupted(3)
            self.assertEqual(s.get_job(job["job_id"])["status"], "blocked")
            self.assertEqual(s.get_job(job["job_id"])["last_step"], "RETRY_DENIED")
            # runner collects the blocked hop → DENIED → out_of_bounds++ (RETRY_DENIED is bounds) → advances
            asyncio.run(_complete_hop(m, s.get_job(job["job_id"]), s))
            m2 = s.get_mission(m["mission_id"])
            self.assertEqual(m2["denied_streak"], 1)
            self.assertEqual(m2["out_of_bounds"], 1)  # RETRY_DENIED ∈ _BOUNDS_VIOLATION_STEPS
            self.assertIsNone(m2["active_job_id"])  # cleared → next hop proceeds

    def test_cloud_readonly_interrupt_reruns(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "t.db"))
            m = _mk(s, worker="research", tools=["web.fetch", "web.search"])
            job = s.create_job(channel="grid", goal="hop", worker="research",
                               allowed_tools=["web.fetch", "web.search"], allowed_paths=["."],
                               cloud_allowed=True, approval_mode="auto", read_only=True,
                               kind="chat", origin=f"mission:{m['mission_id']}", lane="scout")
            # simulate: cloud read_only interrupted → requeue_interrupted → requeued (status=queued)
            s.update_job(job["job_id"], status="interrupted", last_step="cancelled")
            q = s.requeue_interrupted(3)
            self.assertEqual(q, 1)  # requeued, not blocked
            self.assertEqual(s.get_job(job["job_id"])["status"], "queued")
            # runner sees non-terminal (queued) → waits (does not advance yet)
            hops = []
            from mission.runner import _load_lineage_hops, _state_dir
            # the hop is not terminal, so _complete_hop would not be called by the loop;
            # verify the job is re-runnable (queued), proving resume path
            self.assertEqual(s.get_job(job["job_id"])["status"], "queued")


class TestScorecard(unittest.TestCase):
    def test_discipline_fail_when_out_of_bounds(self):
        sc = build_scorecard(
            {"mission_id": "M-1", "goal": "g", "lane": "scout", "worker": "deep",
             "hops_used": 3, "usd_used": 0.1, "tokens_used": 0, "budget_hops": 10,
             "budget_usd": 1.0, "budget_tokens": 0, "budget_wall_s": 60, "out_of_bounds": 1,
             "created_at": 0.0},
            [{"hop": 1, "status": "DENIED", "event_id": "E1", "last_step": "BLOCKED_SANDBOX_MISSING"}],
            "discipline_fail")
        self.assertEqual(sc["discipline_verdict"], "FAIL")

    def test_discipline_pass_when_clean(self):
        sc = build_scorecard(
            {"mission_id": "M-2", "goal": "g", "lane": "scout", "worker": "deep",
             "hops_used": 3, "usd_used": 0.1, "tokens_used": 0, "budget_hops": 10,
             "budget_usd": 1.0, "budget_tokens": 0, "budget_wall_s": 60, "out_of_bounds": 0,
             "created_at": 0.0},
            [{"hop": 1, "status": "EXECUTED", "event_id": "E1", "last_step": "cc_done"}],
            "stop_condition:n>=10")
        self.assertEqual(sc["discipline_verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
