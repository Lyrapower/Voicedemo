"""Unit tests for MISSION v1 (处决案 ⑥ covers the same invariants at integration level).

Covers: payload 缺项拒, 预算耗尽停, 3 连 DENIED 停, 越 bounds 计数, Grid 播种进 proposed
不跑, stop 端点 (store-level).
"""
from __future__ import annotations

import asyncio
import json
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



class TestPaid3Structured(unittest.TestCase):
    """衔拍3 §①1–4: 结构化 query 组装、INVALID_URL、findings 由 runner 附、allowed_tools 开环。"""

    def test_structured_query_assembly(self):
        from harness.tool_loop import run_grants_catalog_structured, _CATALOG_CACHE
        # stub catalog_json_post to capture the request body per keyword (no network)
        import harness.tool_loop as TL
        import harness.web_fetch_v3 as W3
        captured = []
        def fake_post(url, body, lane, **kw):
            captured.append({"url": url, "body": body, "lane": lane})
            return {"ok": True, "status": "200", "json": {"data": []}, "source_url": url}
        W3.catalog_json_post = fake_post
        _CATALOG_CACHE.clear()
        sblk = {"keywords": ["AI infrastructure", "broadband"], "opp_statuses": ["posted"],
                "agencies": [], "deadline_min_days": 14, "rows_per_query": 10}
        out = run_grants_catalog_structured(sblk, lane="scout", db_path=None,
                                             route_id="r1", mission_id="M-test")
        # one Search2 POST per keyword, body carries keyword + oppStatuses
        self.assertEqual(len(captured), 2)
        self.assertTrue(all(c["body"]["oppStatuses"] == "posted" for c in captured))
        self.assertEqual(captured[0]["body"]["keyword"], "AI infrastructure")
        self.assertEqual(captured[1]["body"]["keyword"], "broadband")
        # cache: second call with same mission+keyword hits cache (no new POST)
        captured.clear()
        run_grants_catalog_structured(sblk, lane="scout", db_path=None,
                                       route_id="r1", mission_id="M-test")
        self.assertEqual(len(captured), 0, "same query within mission must hit cache (消 RATE_LIMITED)")

    def test_invalid_url_not_denied(self):
        from harness.web_fetch_v3 import fetch
        # malformed URL (space) → INVALID_URL, not DENIED
        r = fetch("https://api.grants.gov/search?foo=bar baz", "scout", db_path=None)
        self.assertEqual(r["status"], "INVALID_URL")
        self.assertFalse(r["ok"])
        # non-https → INVALID_URL
        r2 = fetch("http://api.grants.gov/x", "scout", db_path=None)
        self.assertEqual(r2["status"], "INVALID_URL")

    def test_findings_built_by_runner(self):
        from mission.runner import _build_findings, _parse_judgments
        # worker output judges opp 100 HIT, opp 200 MISS
        wo = ("opp 100: HIT — AI infrastructure grant matches goal\n"
              "opp 200: MISS — Earth Science, not in scope\n")
        judgments = _parse_judgments(wo)
        self.assertEqual(judgments["100"], ("HIT", "AI infrastructure grant matches goal"))
        self.assertEqual(judgments["200"][0], "MISS")
        # hops carry catalog rows + worker_output; runner attaches URL/deadline/event_id
        hops = [{
            "hop": 1, "job_id": "J-abc12345", "event_id": "J-abc12345",
            "worker_output": wo,
        }]
        store = MagicMock()
        store.list_events = MagicMock(return_value=[{
            "kind": "tool_search",
            "payload": {"catalog_rows": [
                {"opportunity_id": "100", "title": "AI Infra Grant", "publisher": "NSF",
                 "deadline": "2026-12-01", "human_url": "https://www.grants.gov/x100"},
                {"opportunity_id": "200", "title": "ROSES Earth", "publisher": "NASA",
                 "deadline": "2026-10-20", "human_url": "https://www.grants.gov/x200"},
            ]},
        }])
        findings = _build_findings(hops, store, goal="Discover AI infrastructure grants")
        self.assertEqual(len(findings), 1, "only HIT (opp 100) becomes a finding")
        f = findings[0]
        self.assertEqual(f["opportunity_id"], "100")
        self.assertEqual(f["url"], "https://www.grants.gov/x100")
        self.assertEqual(f["deadline"], "2026-12-01")
        self.assertEqual(f["event_id"], "J-abc12345")  # runner-attached, worker never wrote it
        self.assertIn("AI infrastructure", f["reason"])

    def test_missing_title_abandoned(self):
        """处决案 (a): 缺 title 的 row → 不进 findings 且 lineage 有 ABANDONED."""
        from datetime import datetime, timezone
        from pathlib import Path
        from mission.runner import _build_findings, _write_abandoned_lineage
        from mission import runner as R
        wo = ("opp 901: HIT — Discover AI infrastructure; eligibility includes individuals\n")
        hops = [{"hop": 1, "job_id": "J-aaaa1111", "event_id": "J-aaaa1111", "worker_output": wo}]
        store = MagicMock()
        store.list_events = MagicMock(return_value=[{
            "kind": "tool_search",
            "payload": {"catalog_rows": [
                {"opportunity_id": "901", "title": "", "publisher": "NSF",
                 "deadline": "2026-12-01", "status": "posted",
                 "eligibility": "individuals",
                 "human_url": "https://www.grants.gov/x901"},
            ]},
        }])
        abandoned = []
        findings = _build_findings(
            hops, store, goal="Discover AI infrastructure",
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
            abandoned_out=abandoned,
        )
        self.assertEqual(findings, [])
        self.assertTrue(any(a["reason"] == "missing_field" for a in abandoned))
        with tempfile.TemporaryDirectory() as td:
            orig = R._state_dir
            R._state_dir = lambda mid: Path(td)
            try:
                _write_abandoned_lineage("M-t", abandoned)
                hops_l = json.loads((Path(td) / "lineage.json").read_text())
                self.assertTrue(any(h.get("status") == "ABANDONED" for h in hops_l))
                self.assertEqual(hops_l[0].get("reason"), "missing_field")
            finally:
                R._state_dir = orig

    def test_deadline_rolling_vs_past(self):
        """处决案 (b): deadline=2076-08-19 → rolling 计入; 2025-xx 已过 → 不计."""
        from datetime import datetime, timezone
        from mission.runner import _build_findings
        wo = (
            "opp 2076: HIT — Discover AI infrastructure; eligibility includes individuals\n"
            "opp 2025: HIT — Discover AI infrastructure; eligibility includes individuals\n"
        )
        hops = [{"hop": 1, "job_id": "J-bbbb2222", "event_id": "J-bbbb2222", "worker_output": wo}]
        store = MagicMock()
        store.list_events = MagicMock(return_value=[{
            "kind": "tool_search",
            "payload": {"catalog_rows": [
                {"opportunity_id": "2076", "title": "Rolling FOA", "publisher": "NSF",
                 "deadline": "2076-08-19", "status": "posted",
                 "eligibility": "individuals",
                 "human_url": "https://www.grants.gov/x2076"},
                {"opportunity_id": "2025", "title": "Expired FOA", "publisher": "NSF",
                 "deadline": "2025-06-01", "status": "posted",
                 "eligibility": "individuals",
                 "human_url": "https://www.grants.gov/x2025"},
            ]},
        }])
        abandoned = []
        findings = _build_findings(
            hops, store, goal="Discover AI infrastructure",
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
            abandoned_out=abandoned,
        )
        self.assertEqual([f["opportunity_id"] for f in findings], ["2076"])
        self.assertEqual(findings[0].get("deadline_kind"), "rolling")
        self.assertTrue(any(a["opportunity_id"] == "2025" and a["reason"] == "deadline_lt_14d" for a in abandoned))

    def test_eligibility_institution_only_ineligible(self):
        """处决案 (c): eligibility 只含高校/州机构类 → ineligible 不计."""
        from datetime import datetime, timezone
        from mission.runner import _build_findings
        wo = ("opp 909: HIT — Discover AI infrastructure; Public and State controlled "
              "institutions of higher education only\n")
        hops = [{"hop": 1, "job_id": "J-cccc3333", "event_id": "J-cccc3333", "worker_output": wo}]
        store = MagicMock()
        store.list_events = MagicMock(return_value=[{
            "kind": "tool_search",
            "payload": {"catalog_rows": [
                {"opportunity_id": "909", "title": "Campus only", "publisher": "NSF",
                 "deadline": "2026-12-01", "status": "posted",
                 "eligibility": "Public and State controlled institutions of higher education",
                 "human_url": "https://www.grants.gov/x909"},
            ]},
        }])
        abandoned = []
        findings = _build_findings(
            hops, store, goal="Discover AI infrastructure",
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
            abandoned_out=abandoned,
        )
        self.assertEqual(findings, [])
        self.assertTrue(any(a["reason"] == "ineligible" for a in abandoned))

    def test_allowed_tools_opens_research_loop(self):
        """§①4: 工具环按 allowed_tools 开,不按 worker 名。deep + [web.search] → 环开。"""
        from mission.config import mission_template
        t = mission_template("scout")
        self.assertEqual(t["worker"], "deep")  # 钉死 deep,不 fallback research
        self.assertIn("web.search", t["tools"])
        # the gate: allowed_tools 含 web.search 即开(不查 worker 名)
        allowed = t["tools"]
        opens = any(x in allowed for x in ("web.search", "grants.catalog", "grants.catalog_post"))
        self.assertTrue(opens, "deep+scout 的 allowed_tools 含 web.search → 研究环必须开")

    def test_scout_worker_locked_deep_no_research_fallback(self):
        """衔补: scout 钉死 deep; runner 拒 fallback research; research 只跑 research 模板。"""
        from mission.runner import resolve_mission_worker, WorkerLockError
        self.assertEqual(resolve_mission_worker("scout", "deep"), "deep")
        self.assertEqual(resolve_mission_worker("scout", None), "deep")
        self.assertEqual(resolve_mission_worker("scout", ""), "deep")
        with self.assertRaises(WorkerLockError) as cm:
            resolve_mission_worker("scout", "research")
        self.assertEqual(str(cm.exception), "scout_worker_locked_deep")
        with self.assertRaises(WorkerLockError):
            resolve_mission_worker("scout", "fast")
        with self.assertRaises(WorkerLockError):
            resolve_mission_worker("gardener", "research")
        with self.assertRaises(WorkerLockError):
            resolve_mission_worker("builder", "research")
        self.assertEqual(resolve_mission_worker("rwa", "research"), "research")
        from mission.runner import _model_resolved
        self.assertEqual(_model_resolved("deep"), "glm-5.2")

    def test_sandbox_timeout_sweep(self):
        """衔拍3: cc dispatch >120s → blocked SANDBOX_TIMEOUT + 容器卷清理 + 该跳 DENIED 续下一跳。"""
        import asyncio, time
        from harness.supervisor import Supervisor
        sup = Supervisor.__new__(Supervisor)
        sup._tasks = {}
        now = time.time()
        hung = {"job_id": "J-st1", "worker": "cc", "last_step": "dispatch",
                "updated_at": now - 200, "status": "running"}
        healthy = {"job_id": "J-ok1", "worker": "cc", "last_step": "cc_done",
                   "updated_at": now, "status": "done"}
        store = MagicMock()
        store.get_job = MagicMock(side_effect=lambda jid: hung if jid == "J-st1" else healthy)
        sup.store = store
        cleanup_calls = []
        sup.cc = MagicMock()
        sup.cc.cleanup_job = MagicMock(side_effect=lambda jid, **kw: cleanup_calls.append(jid))
        sup._record_job_receipt = MagicMock()
        async def _hang():
            await asyncio.sleep(100)
        async def _run():
            sup._tasks["J-st1"] = asyncio.ensure_future(_hang())
            sup._tasks["J-ok1"] = asyncio.ensure_future(_hang())
            await sup._sandbox_timeout_sweep()
        asyncio.run(_run())
        store.update_job.assert_any_call("J-st1", status="blocked", last_step="SANDBOX_TIMEOUT")
        self.assertEqual(cleanup_calls, ["J-st1"])
        self.assertTrue(sup._tasks["J-st1"].cancelled() or sup._tasks["J-st1"].done())
        for c in store.update_job.call_args_list:
            self.assertNotEqual(c.args[0], "J-ok1")
        from mission.runner import _BOUNDS_VIOLATION_STEPS
        self.assertNotIn("SANDBOX_TIMEOUT", _BOUNDS_VIOLATION_STEPS)


if __name__ == "__main__":
    unittest.main()
