import json, os, tempfile, unittest
from bridge_kit import web_search_ollama as wo
from bridge_kit import web_search_brave as wb

BODY = json.dumps({"results": [
    {"title": "Ollama", "url": "https://ollama.com/", "content": "Cloud models are now available..."},
    {"title": "no url"},
    {"title": "Electron", "url": "https://www.electronjs.org/", "content": "x" * 900},
]})
KEY = "ollama-secret-key"


def make_post(code=200, body=BODY):
    calls = []
    def post(url, headers, body_json):
        calls.append((url, dict(headers), json.loads(body_json)))
        return code, body
    post.calls = calls
    return post


def counter():
    return wb.MonthlyCounter(os.path.join(tempfile.mkdtemp(), "ollama_month.json"))


class T(unittest.TestCase):
    def test_execution_no_key_no_network(self):
        p = make_post()
        r = wo.search("electron", p, counter(), lambda d: True, env={})
        self.assertEqual(r["error"], "SEARCH_UNAVAILABLE"); self.assertEqual(p.calls, [])

    def test_execution_egress_not_registered_no_network(self):
        p = make_post()
        r = wo.search("electron", p, counter(), lambda d: d != "ollama.com", env={wo.ENV_KEY: KEY})
        self.assertEqual(r["error"], "DENIED_EGRESS_NOT_REGISTERED"); self.assertEqual(p.calls, [])

    def test_ok_shape_matches_official_doc_and_key_never_leaks(self):
        p = make_post(); c = counter()
        r = wo.search("electron", p, c, lambda d: d == "ollama.com", max_results=50, env={wo.ENV_KEY: KEY})
        self.assertEqual(r["status"], "ok"); self.assertEqual(r["n_results"], 2)
        self.assertEqual(set(r["results"][0]), {"title", "url", "snippet"})
        self.assertEqual(len(r["results"][1]["snippet"]), 500)
        self.assertNotIn(KEY, json.dumps(r))
        url, headers, body = p.calls[0]
        self.assertEqual(url, "https://ollama.com/api/web_search")
        self.assertEqual(headers["Authorization"], "Bearer " + KEY)
        self.assertEqual(body, {"query": "electron", "max_results": 10})  # 官方最大 10
        self.assertEqual(c.used(), 1)

    def test_execution_cap_zero_means_count_only(self):
        p = make_post(); c = counter()
        for _ in range(3):
            wo.search("q", p, c, lambda d: True, env={wo.ENV_KEY: KEY})
        self.assertEqual(c.used(), 3); self.assertEqual(len(p.calls), 3)

    def test_execution_cap_set_blocks(self):
        p = make_post(); c = counter(); env = {wo.ENV_KEY: KEY, wo.ENV_CAP: "1"}
        wo.search("a", p, c, lambda d: True, env=env)
        r = wo.search("b", p, c, lambda d: True, env=env)
        self.assertEqual(r["error"], "SEARCH_BUDGET_EXHAUSTED"); self.assertEqual(len(p.calls), 1)

    def test_execution_401_429_500_bad_json(self):
        for code, body, name, retry in ((401, "", "SEARCH_AUTH_401", False), (429, "", "SEARCH_RATE_LIMITED", True),
                                        (500, "", "SEARCH_HTTP_500", True), (200, "<html>", "SEARCH_BAD_JSON", False)):
            r = wo.search("x", make_post(code, body), counter(), lambda d: True, env={wo.ENV_KEY: KEY})
            self.assertEqual(r["error"], name); self.assertEqual(r["retryable"], retry)

    def test_execution_no_validator_denies(self):
        p = make_post()
        r = wo.search("x", p, counter(), None, env={wo.ENV_KEY: KEY})
        self.assertEqual(r["error"], "DENIED_EGRESS_NOT_REGISTERED"); self.assertEqual(p.calls, [])

    def test_fallback_ollama_first_then_brave_skips_keyless(self):
        ollama_ok = lambda q: {"status": "ok", "provider": "ollama", "results": [1]}
        brave_nokey = lambda q: {"status": "error", "error": "SEARCH_UNAVAILABLE", "provider": "brave"}
        r = wo.search_with_fallback("q", [("ollama", ollama_ok), ("brave", brave_nokey)])
        self.assertEqual(r["provider"], "ollama"); self.assertEqual(r["tried"], [("ollama", "ok", None)])
        ollama_down = lambda q: {"status": "error", "error": "SEARCH_HTTP_503", "provider": "ollama"}
        r = wo.search_with_fallback("q", [("ollama", ollama_down), ("brave", brave_nokey)])
        self.assertEqual(r["error"], "SEARCH_UNAVAILABLE")
        self.assertEqual([t[0] for t in r["tried"]], ["ollama", "brave"])
        brave_ok = lambda q: {"status": "ok", "provider": "brave", "results": [1]}
        r = wo.search_with_fallback("q", [("ollama", ollama_down), ("brave", brave_ok)])
        self.assertEqual(r["provider"], "brave")

if __name__ == "__main__":
    unittest.main()
