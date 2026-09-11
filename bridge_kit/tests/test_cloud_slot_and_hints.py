import threading
import unittest

from bridge_kit import cloud_slot as cs
from bridge_kit import tool_hints as th


class Fake8501(object):
    """running_max=1:第二个并发请求回 429。"""

    def __init__(self, running_max=1):
        self.running_max = running_max
        self._lock = threading.Lock()
        self._running = 0
        self.n429 = 0

    def chat(self):
        with self._lock:
            if self._running >= self.running_max:
                self.n429 += 1
                return {"code": 429}
            self._running += 1
        try:
            return {"code": 200}
        finally:
            with self._lock:
                self._running -= 1


class TSlot(unittest.TestCase):
    def test_execution_three_parallel_jobs_bounded_and_no_dup_side_effects(self):
        srv = Fake8501(running_max=1)
        slot = cs.CloudSlot(max_running=1)
        results, errs, sent = [], [], []

        def call():
            sent.append(1)
            return srv.chat()

        def job():
            try:
                resp, attempts, waited = cs.run_with_backoff(
                    slot, call, lambda r: r["code"], base=1, sleep=lambda s: None, rng=lambda: 0.5)
                results.append((resp["code"], attempts))
            except Exception as e:  # noqa
                errs.append(e)

        ts = [threading.Thread(target=job) for _ in range(3)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(errs, [])
        self.assertEqual([r[0] for r in results], [200, 200, 200])
        self.assertEqual(slot.peak_concurrent, 1)          # 本进程并发不超上限
        self.assertEqual(len(sent), 3)                     # 每个 job 恰好发一次,无重复副作用

    def test_execution_429_counts_attempts_and_waits_outside_slot(self):
        seq = [{"code": 429}, {"code": 429}, {"code": 200}]
        slot = cs.CloudSlot(1)
        slept = []
        in_slot_during_sleep = []

        def sleep(s):
            slept.append(s)
            in_slot_during_sleep.append(slot._cur)

        resp, attempts, waited = cs.run_with_backoff(slot, lambda: seq.pop(0), lambda r: r["code"],
                                                     base=30, cap=600, sleep=sleep, rng=lambda: 0.5)
        self.assertEqual(resp["code"], 200)
        self.assertEqual(attempts, 3)
        self.assertEqual(slept, [30, 60])                  # rng=0.5 → 抖动因子 1.0
        self.assertEqual(in_slot_during_sleep, [0, 0])     # 等待时不占槽

    def test_execution_retry_after_is_a_floor_jitter_cannot_shorten_it(self):
        seq = [{"code": 429, "headers": {"Retry-After": "7"}}, {"code": 200}]
        slept = []
        cs.run_with_backoff(cs.CloudSlot(1), lambda: seq.pop(0), lambda r: r["code"],
                            base=1, sleep=slept.append, rng=lambda: 0.0)  # 抖动取最小 0.5x
        self.assertEqual(slept, [7])          # 仍不早于 Retry-After
        seq = [{"code": 429, "headers": {"Retry-After": "7"}}, {"code": 200}]
        slept = []
        cs.run_with_backoff(cs.CloudSlot(1), lambda: seq.pop(0), lambda r: r["code"],
                            base=30, sleep=slept.append, rng=lambda: 0.5)
        self.assertEqual(slept, [30])         # 退避比 Retry-After 长时取长的

    def test_execution_deadline_not_double_deducted(self):
        """真实时钟:now 已含已等的时间。deadline 100,等 30+60=90 后第三次还该允许(旧码扣两次会在 60 处误停)。"""
        clock = [0.0]
        def now(): return clock[0]
        def sleep(s): clock[0] += s
        seq = [{"code": 429}, {"code": 429}, {"code": 200}]
        resp, attempts, waited = cs.run_with_backoff(cs.CloudSlot(1), lambda: seq.pop(0), lambda r: r["code"],
                                                     base=30, cap=600, deadline_s=100, sleep=sleep, now=now, rng=lambda: 0.5)
        self.assertEqual((resp["code"], attempts, waited), (200, 3, 90))
        clock[0] = 0.0
        seq = [{"code": 429}, {"code": 429}, {"code": 429}, {"code": 200}]
        with self.assertRaises(cs.BackoffExhausted):  # 第三次要等 120,超 100 才停
            cs.run_with_backoff(cs.CloudSlot(1), lambda: seq.pop(0), lambda r: r["code"],
                                base=30, cap=600, deadline_s=100, sleep=sleep, now=now, rng=lambda: 0.5)

    def test_execution_max_attempts_and_deadline_bound(self):
        with self.assertRaises(cs.BackoffExhausted):
            cs.run_with_backoff(cs.CloudSlot(1), lambda: {"code": 429}, lambda r: r["code"],
                                base=1, max_attempts=3, sleep=lambda s: None, rng=lambda: 0.5)
        with self.assertRaises(cs.BackoffExhausted):
            cs.run_with_backoff(cs.CloudSlot(1), lambda: {"code": 503}, lambda r: r["code"],
                                base=100, cap=1000, deadline_s=150, sleep=lambda s: None, rng=lambda: 0.5)

    def test_execution_4xx_not_retried(self):
        n = []
        resp, attempts, _ = cs.run_with_backoff(cs.CloudSlot(1), lambda: (n.append(1) or {"code": 401}),
                                                lambda r: r["code"], sleep=lambda s: None)
        self.assertEqual((resp["code"], attempts, len(n)), (401, 1, 1))

    def test_execution_bad_max_running_rejected(self):
        with self.assertRaises(ValueError):
            cs.CloudSlot(0)


class THints(unittest.TestCase):
    def test_execution_grants_search2_via_web_fetch_blocked(self):
        r = th.check_web_fetch_url("https://api.grants.gov/v1/api/search2")
        self.assertEqual(r["error"], "INVALID_TOOL_CALL")
        r = th.check_web_fetch_url("https://api.grants.gov/v1/api/search2/")
        self.assertEqual(r["error"], "INVALID_TOOL_CALL")

    def test_other_urls_pass(self):
        self.assertIsNone(th.check_web_fetch_url("https://api.github.com/zen"))
        self.assertIsNone(th.check_web_fetch_url("https://api.grants.gov/v1/api/fetchOpportunity"))

    def test_execution_worker_name_never_grants_lane(self):
        with self.assertRaises(th.LaneMissing):
            th.lane_for_job({"jid": "J-1", "worker": "flash"})
        with self.assertRaises(th.LaneMissing):
            th.lane_for_job({"jid": "J-1", "worker": "deep"})  # 连同名都不算
        with self.assertRaises(th.LaneMissing):
            th.lane_for_job({"jid": "J-1", "worker": "flash", "lane": "root"})

    def test_lane_comes_from_job_field_only(self):
        self.assertEqual(th.lane_for_job({"jid": "J-1", "worker": "flash", "lane": "deep"}), "deep")
        self.assertEqual(th.lane_for_job({"jid": "J-2", "worker": "deep", "lane": "scout"}), "scout")

    def test_execution_ddg_challenge_marked_not_content(self):
        body = "<html>...Please complete the captcha... error 410b</html>"
        r = th.annotate_semantic({"status": "ok", "chars": 430}, body)
        self.assertEqual(r["semantic"], "challenge")
        r = th.annotate_semantic({"status": "ok"}, "Keep it logically awesome.")
        self.assertEqual(r["semantic"], "content")
        r = th.annotate_semantic({"status": "ok"}, "   ")
        self.assertEqual(r["semantic"], "empty")

    def test_search_unavailable_is_not_retryable(self):
        r = th.search_unavailable("electron")
        self.assertEqual(r["error"], "SEARCH_UNAVAILABLE")
        self.assertFalse(r["retryable"])


if __name__ == "__main__":
    unittest.main()
