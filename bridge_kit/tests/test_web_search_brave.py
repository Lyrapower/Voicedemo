import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from bridge_kit import web_search_brave as ws

BODY = json.dumps({
    "query": {"original": "electron", "more_results_available": True},
    "web": {"results": [
        {"title": "Electron | Build cross-platform desktop apps", "url": "https://www.electronjs.org/",
         "description": "Electron is a framework..."},
        {"title": "no url item"},
        {"title": "Electron - Wikipedia", "url": "https://en.wikipedia.org/wiki/Electron",
         "description": "subatomic particle"},
    ]},
})
KEY = "BSA-secret-key-123"


def make_get(code=200, body=BODY):
    calls = []

    def get(url, headers):
        calls.append((url, dict(headers)))
        return code, body
    get.calls = calls
    return get


def counter(now=None):
    d = tempfile.mkdtemp()
    return ws.MonthlyCounter(os.path.join(d, "brave_month.json"), now=now)


class T(unittest.TestCase):
    def test_execution_no_key_no_network(self):
        get = make_get()
        r = ws.search("electron", get, counter(), lambda d: True, env={})
        self.assertEqual(r["error"], "SEARCH_UNAVAILABLE")
        self.assertFalse(r["retryable"])
        self.assertEqual(get.calls, [])

    def test_execution_egress_not_registered_no_network(self):
        get = make_get()
        r = ws.search("electron", get, counter(), lambda d: False, env={ws.ENV_KEY: KEY})
        self.assertEqual(r["error"], "DENIED_EGRESS_NOT_REGISTERED")
        self.assertEqual(get.calls, [])

    def test_ok_normalized_and_key_never_in_receipt(self):
        get = make_get()
        c = counter()
        r = ws.search("electron", get, c, lambda d: d == ws.DOMAIN, env={ws.ENV_KEY: KEY})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["n_results"], 2)  # 无 url 的丢
        self.assertEqual(r["results"][0]["url"], "https://www.electronjs.org/")
        self.assertEqual(set(r["results"][0].keys()), {"title", "url", "snippet"})
        self.assertTrue(r["more"])
        self.assertEqual(r["grade"], "unverified")
        self.assertNotIn(KEY, json.dumps(r))
        url, headers = get.calls[0]
        self.assertTrue(url.startswith("https://api.search.brave.com/res/v1/web/search?q=electron&count=10&offset=0"))
        self.assertEqual(headers["X-Subscription-Token"], KEY)
        self.assertEqual(c.used(), 1)

    def test_execution_monthly_cap_blocks_before_network(self):
        get = make_get()
        c = counter()
        env = {ws.ENV_KEY: KEY, ws.ENV_CAP: "2"}
        ws.search("a", get, c, lambda d: True, env=env)
        ws.search("b", get, c, lambda d: True, env=env)
        r = ws.search("c", get, c, lambda d: True, env=env)
        self.assertEqual(r["error"], "SEARCH_BUDGET_EXHAUSTED")
        self.assertEqual(len(get.calls), 2)
        self.assertEqual(c.used(), 2)

    def test_execution_counter_survives_restart_and_resets_on_new_month(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "m.json")
        sep = lambda: datetime(2026, 9, 10, tzinfo=timezone.utc)
        c1 = ws.MonthlyCounter(p, now=sep)
        c1.increment(); c1.increment()
        c2 = ws.MonthlyCounter(p, now=sep)  # 重启
        self.assertEqual(c2.used(), 2)
        c3 = ws.MonthlyCounter(p, now=lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(c3.used(), 0)

    def test_execution_failed_request_still_counts(self):
        get = make_get(code=500, body="")
        c = counter()
        r = ws.search("x", get, c, lambda d: True, env={ws.ENV_KEY: KEY})
        self.assertEqual(r["error"], "SEARCH_HTTP_500")
        self.assertTrue(r["retryable"])
        self.assertEqual(c.used(), 1)

    def test_execution_401_429_422_named(self):
        for code, name, retry in ((401, "SEARCH_AUTH_401", False), (429, "SEARCH_RATE_LIMITED", True),
                                  (422, "SEARCH_BAD_QUERY", False)):
            r = ws.search("x", make_get(code=code, body=""), counter(), lambda d: True, env={ws.ENV_KEY: KEY})
            self.assertEqual(r["error"], name)
            self.assertEqual(r["retryable"], retry)

    def test_execution_bad_json(self):
        r = ws.search("x", make_get(body="<html>"), counter(), lambda d: True, env={ws.ENV_KEY: KEY})
        self.assertEqual(r["error"], "SEARCH_BAD_JSON")

    def test_execution_no_egress_validator_means_deny_not_allow(self):
        get = make_get()
        r = ws.search("x", get, counter(), None, env={ws.ENV_KEY: KEY})
        self.assertEqual(r["error"], "DENIED_EGRESS_NOT_REGISTERED")
        self.assertEqual(get.calls, [])

    def test_execution_corrupt_counter_does_not_reset_to_zero(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "m.json")
        with open(p, "w") as f:
            f.write("{not json")
        c = ws.MonthlyCounter(p)
        with self.assertRaises(ws.CounterCorrupt):
            c.used()
        get = make_get()
        r = ws.search("x", get, c, lambda d: True, env={ws.ENV_KEY: KEY})
        self.assertEqual(r["error"], "SEARCH_QUOTA_COUNTER_CORRUPT")
        self.assertEqual(get.calls, [])
        with open(p, "w") as f:
            f.write(json.dumps({"month": "2026-09"}))  # 缺 n 也算坏
        with self.assertRaises(ws.CounterCorrupt):
            ws.MonthlyCounter(p).used()

    def test_execution_two_processes_cap_1_only_one_reserves(self):
        import multiprocessing, sys
        d = tempfile.mkdtemp(); p = os.path.join(d, "m.json")
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from bridge_kit.web_search_brave import MonthlyCounter\n"
            "import json\n"
            "c = MonthlyCounter(%r)\n"
            "got = [c.reserve(1) for _ in range(50)]\n"
            "print(json.dumps(sum(1 for g in got if g is not None)))\n"
        ) % (os.getcwd(), p)
        import subprocess
        procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE) for _ in range(4)]
        outs = [int(pr.communicate()[0].decode().strip()) for pr in procs]
        self.assertEqual(sum(outs), 1)
        self.assertEqual(ws.MonthlyCounter(p).used(), 1)

    def test_execution_four_processes_increment_no_lost_updates(self):
        import sys, subprocess
        d = tempfile.mkdtemp(); p = os.path.join(d, "m.json")
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from bridge_kit.web_search_brave import MonthlyCounter\n"
            "c = MonthlyCounter(%r)\n"
            "[c.increment() for _ in range(25)]\n"
        ) % (os.getcwd(), p)
        procs = [subprocess.Popen([sys.executable, "-c", code]) for _ in range(4)]
        for pr in procs: pr.wait()
        self.assertEqual(ws.MonthlyCounter(p).used(), 100)

    def test_count_clamped_to_20(self):
        get = make_get()
        ws.search("x", get, counter(), lambda d: True, count=500, env={ws.ENV_KEY: KEY})
        self.assertIn("count=20", get.calls[0][0])


if __name__ == "__main__":
    unittest.main()
