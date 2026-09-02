"""factor_evolution 测试 + 进化链路冒烟(QuantaAlpha trajectory mutation/crossover + RD-Agent(Q) bandit)。

覆盖:
  - trajectory schema/reward/query
  - bandit UCB 选向(未试 arm 优先探索 + exploit/explore 平衡)
  - mutation/crossover/direction prompt 构建
  - decide_evolve 决策序(mutation > crossover > propose)
  - 端到端冒烟:stub factory_task,跑 evolve_factor → review → trajectory 落表 + lineage 可追
  - 沙箱主权不破(metrics 仍由 factor_sandbox 算,LLM 输出不进 metrics)
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
os.environ.setdefault("PLATFORM_DB_DIRECT_WRITE", "1")

import factor_evolution as FE
import factory_prompts as FP


def _fresh_db() -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, mode="w")
    tmp.close()
    os.environ["PLATFORM_DB"] = tmp.name
    return tmp.name


class TrajectoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.db_path = _fresh_db()
        import importlib
        import db
        importlib.reload(db)
        self.c = db.conn_factory()
        FE.ensure_trajectory_schema(self.c)

    def tearDown(self):
        self.c.close()
        os.unlink(self.db_path)
        os.environ.pop("PLATFORM_DB", None)

    def test_reward_passed_uses_abs_ic(self):
        r, ic, ir = FE.compute_reward({"ic": 0.15, "ir": 1.2}, "passed")
        self.assertAlmostEqual(r, 0.15)
        self.assertEqual(ic, 0.15)
        self.assertEqual(ir, 1.2)

    def test_reward_negative_ic_still_abs(self):
        r, _, _ = FE.compute_reward({"ic": -0.08}, "passed")
        self.assertAlmostEqual(r, 0.08)

    def test_reward_rejected_is_zero(self):
        r, ic, ir = FE.compute_reward({"ic": 0.2}, "rejected")
        self.assertEqual(r, 0.0)
        self.assertIsNone(ic)

    def test_record_and_top_trajectories(self):
        FE.record_trajectory(self.c, draft_id=1, review_id=None, hypothesis="mom",
                             code="def factor(df): return df.c.pct_change()", metrics={"ic": 0.12, "ir": 0.8},
                             outcome="passed", origin="propose", direction="momentum")
        FE.record_trajectory(self.c, draft_id=2, review_id=None, hypothesis="rev",
                             code="def factor(df): return -df.c.pct_change()", metrics={"ic": 0.20, "ir": 1.1},
                             outcome="passed", origin="propose", direction="mean_reversion")
        FE.record_trajectory(self.c, draft_id=3, review_id=None, hypothesis="bad",
                             code="def factor(df): return df.c", metrics=None,
                             outcome="rejected", origin="propose", direction="volume",
                             meta={"rejection_error": "KeyError: 'x'"})
        top = FE.top_trajectories(self.c, limit=10)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0]["hypothesis"], "rev")  # reward 0.20 > 0.12
        rej = FE.recent_rejected(self.c, limit=10)
        self.assertEqual(len(rej), 1)
        self.assertEqual(rej[0]["meta"]["rejection_error"], "KeyError: 'x'")

    def test_lineage_chain(self):
        tid1 = FE.record_trajectory(self.c, draft_id=1, review_id=None, hypothesis="h1", code="c1",
                                     metrics={"ic": 0.1}, outcome="passed", origin="propose", direction="momentum")
        tid2 = FE.record_trajectory(self.c, draft_id=2, review_id=None, hypothesis="h2", code="c2",
                                     metrics=None, outcome="rejected", origin="mutation", direction="momentum",
                                     parent_id=tid1)
        chain = FE.trajectory_lineage(self.c, tid2)
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0]["id"], tid2)
        self.assertEqual(chain[1]["id"], tid1)  # parent


class BanditUCBTest(unittest.TestCase):
    def setUp(self):
        self.db_path = _fresh_db()
        import importlib
        import db
        importlib.reload(db)
        self.c = db.conn_factory()
        FE.ensure_trajectory_schema(self.c)

    def tearDown(self):
        self.c.close()
        os.unlink(self.db_path)
        os.environ.pop("PLATFORM_DB", None)

    def test_untried_arms_explored_first(self):
        # 无任何 trajectory → 选第一个 arm(未试 bonus)
        arm = FE.ucb_select(self.c)
        self.assertIn(arm, FE.directions())

    def test_exploit_after_data(self):
        # momentum 有高 reward,其它 0 → UCB 应倾向 momentum(足够多轮后)
        for _ in range(5):
            FE.record_trajectory(self.c, draft_id=None, review_id=None, hypothesis="m", code="c",
                                 metrics={"ic": 0.3, "ir": 1.5}, outcome="passed",
                                 origin="propose", direction="momentum")
        for _ in range(5):
            FE.record_trajectory(self.c, draft_id=None, review_id=None, hypothesis="v", code="c",
                                 metrics=None, outcome="rejected", origin="propose", direction="volume")
        # 跑 20 次选向,momentum 应被选多数(exploit 主导)
        picks = [FE.ucb_select(self.c) for _ in range(20)]
        self.assertGreater(picks.count("momentum"), picks.count("volume"))

    def test_forced_direction_overrides_bandit(self):
        # decide_evolve 传 direction 应直接用,不调 ucb
        dec = FE.decide_evolve(self.c, direction="earnings_drift")
        self.assertEqual(dec.direction, "earnings_drift")


class PromptBuildTest(unittest.TestCase):
    def test_mutate_prompt_has_parent_code_and_frozen_hypothesis(self):
        txt = FP.build_factory_task("mutate", {
            "parent_hypothesis": "动量假设",
            "parent_code": "def factor(df): return df.c.pct_change(5)",
            "rejection_error": "KeyError: 'missing_col'",
            "rejection_detail": {"ast_scan": "pass"},
        })
        self.assertIn("冻结", txt)
        self.assertIn("动量假设", txt)
        self.assertIn("def factor(df)", txt)
        self.assertIn("KeyError", txt)

    def test_crossover_prompt_has_both_parents(self):
        txt = FP.build_factory_task("crossover", {
            "parent_hypothesis": "A假设", "parent_code": "def factor(df): return df.c.pct_change()",
            "parent_b_hypothesis": "B假设", "parent_b_code": "def factor(df): return -df.c.diff()",
        })
        self.assertIn("A假设", txt)
        self.assertIn("B假设", txt)
        self.assertIn("继承父 A", txt)

    def test_direction_prompt_has_direction_and_fewshot(self):
        txt = FP.build_factory_task("direction", {
            "direction": "overnight_gap",
            "knowledge_examples": [{"hypothesis": "gap reversal"}],
        })
        self.assertIn("overnight_gap", txt)
        self.assertIn("gap reversal", txt)
        self.assertIn("勿复刻", txt)

    def test_parse_factory_result_extracts_code_and_hypothesis(self):
        out = FP.parse_factory_result("mutate", "假设说明:修了列名\n\n```python\ndef factor(df): return df.c\n```")
        self.assertEqual(out["code"], "def factor(df): return df.c")
        self.assertEqual(out["hypothesis"], "修了列名")


class EvolveSmokeTest(unittest.TestCase):
    """端到端冒烟:stub factory_task,跑 evolve_factor → review → trajectory 落表 + lineage。
    验证:沙箱主权(metrics 由 factor_sandbox 算,非 stub)、GLM 编译闸路径不破、trajectory lineage 可追。"""

    def setUp(self):
        self.db_path = _fresh_db()
        import importlib
        import db
        importlib.reload(db)
        # 需要一个有 bars 数据的 db 让沙箱能跑;造最小 bars
        c = db.conn()
        syms = ["AAPL", "MSFT"]
        base_ts = 1700000000
        rows = []
        for sym in syms:
            for i in range(40):
                rows.append((base_ts + i * 60, sym, 100 + i * 0.1, 101 + i * 0.1, 99 + i * 0.1, 100.5 + i * 0.1, 1000 + i))
        c.executemany("INSERT INTO bars(ts, symbol, o, h, l, c, v) VALUES(?,?,?,?,?,?,?)", rows)
        c.commit()
        c.close()
        self._orig_watchlist = os.getenv("WATCHLIST")
        os.environ["WATCHLIST"] = "AAPL,MSFT"

    def tearDown(self):
        os.unlink(self.db_path)
        os.environ.pop("PLATFORM_DB", None)
        if self._orig_watchlist is not None:
            os.environ["WATCHLIST"] = self._orig_watchlist
        else:
            os.environ.pop("WATCHLIST", None)

    def _stub_factory_task(self, kind, payload, budget_hint="std", trace_id=None):
        """stub LLM:返回一个能过沙箱的简单因子。direction/mutate/crossover/propose 都返回同一份。"""
        return {
            "ok": True,
            "code": "def factor(df):\n    return df.groupby('symbol')['c'].pct_change(5).reset_index(level=0, drop=True)",
            "hypothesis": "stub 假设:%s" % kind,
            "route": "stub",
            "trace_id": "stub-trace",
            "substrate": "stub",
        }

    def test_evolve_factor_propose_origin_records_trajectory(self):
        import importlib
        import factory_pipeline
        importlib.reload(factory_pipeline)
        with patch("factory_pipeline.factory_task", side_effect=self._stub_factory_task):
            with patch("factory_pipeline.factor_sandbox.run_factor_review",
                       return_value={"ic": 0.05, "ir": 0.4, "n_obs": 80, "symbols": 2}):
                # 第一轮:无 trajectory → propose(bandit 选向)
                res = factory_pipeline.evolve_factor(test=True)
                self.assertEqual(res["status"], "draft")
                self.assertIn(res["origin"], ("propose", "mutation", "crossover"))
                draft_id = res["draft_id"]
                # 跑 review(同步等待:直接调 _run_review_job 用 stub)
                # 由于 _run_review_job 是线程,我们直接验证 trajectory 在 review 后落表
                # 这里用 start_review + 轮询 job 状态
                job_id = factory_pipeline.start_review(draft_id)
                # 等线程完成
                import time as _t
                for _ in range(40):
                    import db as _db
                    jc = _db.conn_jobs()
                    row = jc.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
                    jc.close()
                    if row and row[0] == "done":
                        break
                    _t.sleep(0.2)
                # 验 trajectory 落表
                import db as _db
                c = _db.conn_factory()
                FE.ensure_trajectory_schema(c)
                trajs = c.execute("SELECT outcome, origin, direction FROM factor_trajectories").fetchall()
                c.close()
                self.assertGreater(len(trajs), 0, "trajectory 未落表")
                outcomes = [t[0] for t in trajs]
                self.assertIn(outcomes[0], ("passed", "quarantine", "rejected"))

    def test_mutation_after_rejected_trajectory(self):
        """先造一条 rejected trajectory,再 evolve → 应选 mutation origin。"""
        import importlib
        import factory_pipeline
        importlib.reload(factory_pipeline)
        import db
        c = db.conn_factory()
        FE.ensure_trajectory_schema(c)
        # 造一条 rejected trajectory(有 rejection_error,可被 mutation)
        FE.record_trajectory(c, draft_id=999, review_id=None, hypothesis="失败假设", code="def factor(df): return df.x",
                             metrics=None, outcome="rejected", origin="propose", direction="momentum",
                             meta={"rejection_error": "KeyError: 'x'", "rejection_detail": {"ast_scan": "pass"}})
        c.commit()
        c.close()
        with patch("factory_pipeline.factory_task", side_effect=self._stub_factory_task):
            res = factory_pipeline.evolve_factor(test=True)
            self.assertEqual(res["origin"], "mutation", "有 rejected trajectory 应选 mutation")
            self.assertEqual(res["parent_id"], 1)  # 第一条 trajectory id

    def test_crossover_after_two_passed_trajectories(self):
        """先造两条 passed 高 reward trajectory,再 evolve(mutation_first=False)→ 应选 crossover。"""
        import importlib
        import factory_pipeline
        importlib.reload(factory_pipeline)
        import db
        c = db.conn_factory()
        FE.ensure_trajectory_schema(c)
        FE.record_trajectory(c, draft_id=None, review_id=None, hypothesis="A", code="def factor(df): return df.c.pct_change()",
                             metrics={"ic": 0.15, "ir": 1.0}, outcome="passed", origin="propose", direction="momentum")
        FE.record_trajectory(c, draft_id=None, review_id=None, hypothesis="B", code="def factor(df): return -df.c.diff()",
                             metrics={"ic": 0.18, "ir": 1.2}, outcome="passed", origin="propose", direction="mean_reversion")
        c.commit()
        c.close()
        with patch("factory_pipeline.factory_task", side_effect=self._stub_factory_task):
            res = factory_pipeline.evolve_factor(test=True, mutation_first=False)
            self.assertEqual(res["origin"], "crossover")
            self.assertIsNotNone(res["parent_id"])
            self.assertIsNotNone(res["crossover_parent_b"])

    def test_sandbox_sovereignty_not_broken(self):
        """沙箱主权:metrics 必须由 factor_sandbox 算,stub 的 LLM 输出不进 metrics。
        这里直接验 run_factor_review 仍只接受 code、独立算 metrics,不接受外部 metrics。"""
        import factor_sandbox
        import db
        code = "def factor(df):\n    return df.groupby('symbol')['c'].pct_change(5).reset_index(level=0, drop=True)"
        metrics = factor_sandbox.run_factor_review(code, self.db_path, ["AAPL", "MSFT"])
        # metrics 字段全由沙箱算,不含 LLM 输出
        self.assertIn("ic", metrics)
        self.assertIn("ir", metrics)
        self.assertEqual(metrics["computed_by"], "alpha-platform/factor_sandbox")
        self.assertNotIn("hypothesis", metrics)  # LLM 的 hypothesis 不该进 metrics


class EvolveLoopTest(unittest.TestCase):
    """evolve_loop(rounds=N) 自动循环:stub LLM + 沙箱,跑 15 轮,验 trajectory 落表 + 汇总。"""

    def setUp(self):
        self.db_path = _fresh_db()
        import importlib
        import db
        importlib.reload(db)
        c = db.conn()
        syms = ["AAPL", "MSFT"]
        base_ts = 1700000000
        rows = []
        for sym in syms:
            for i in range(40):
                rows.append((base_ts + i * 60, sym, 100 + i * 0.1, 101 + i * 0.1, 99 + i * 0.1, 100.5 + i * 0.1, 1000 + i))
        c.executemany("INSERT INTO bars(ts, symbol, o, h, l, c, v) VALUES(?,?,?,?,?,?,?)", rows)
        c.commit()
        c.close()
        self._orig_watchlist = os.getenv("WATCHLIST")
        os.environ["WATCHLIST"] = "AAPL,MSFT"

    def tearDown(self):
        os.unlink(self.db_path)
        os.environ.pop("PLATFORM_DB", None)
        if self._orig_watchlist is not None:
            os.environ["WATCHLIST"] = self._orig_watchlist
        else:
            os.environ.pop("WATCHLIST", None)

    def _stub_factory_task(self, kind, payload, budget_hint="std", trace_id=None):
        return {
            "ok": True,
            "code": "def factor(df):\n    return df.groupby('symbol')['c'].pct_change(5).reset_index(level=0, drop=True)",
            "hypothesis": "stub 假设:%s" % kind,
            "route": "stub",
            "trace_id": "stub-trace",
            "substrate": "stub",
        }

    def test_evolve_loop_15_rounds(self):
        import importlib
        import factory_pipeline
        importlib.reload(factory_pipeline)
        round_logs = []
        with patch("factory_pipeline.factory_task", side_effect=self._stub_factory_task):
            with patch("factory_pipeline.factor_sandbox.run_factor_review",
                       return_value={"ic": 0.05, "ir": 0.4, "n_obs": 80, "symbols": 2}):
                summary = factory_pipeline.evolve_loop(
                    rounds=15, test=True, poll_timeout=10.0,
                    on_round=lambda i, info: round_logs.append(info),
                )
        self.assertEqual(summary["rounds"], 15)
        self.assertEqual(len(round_logs), 15, "on_round 应被调 15 次")
        outcomes = summary["outcomes"]
        self.assertGreater(sum(outcomes.get(k, 0) for k in ("passed", "quarantine", "rejected")), 0)
        self.assertGreater(summary["best_reward"], 0)
        self.assertIsNotNone(summary["best_direction"])
        self.assertGreaterEqual(summary["lineage_depth"], 1)

    def test_evolve_loop_handles_factory_error(self):
        """factory_task 抛错 → 记 factory_error,不崩,继续下一轮。"""
        import importlib
        import factory_pipeline
        importlib.reload(factory_pipeline)

        def flaky_task(kind, payload, budget_hint="std", trace_id=None):
            raise factory_pipeline.FactoryGridError("stub 槽满")

        with patch("factory_pipeline.factory_task", side_effect=flaky_task):
            summary = factory_pipeline.evolve_loop(rounds=3, test=True, poll_timeout=5.0)
        self.assertEqual(summary["outcomes"].get("factory_error"), 3)
        self.assertEqual(summary["best_reward"], 0.0)


if __name__ == "__main__":
    unittest.main()
