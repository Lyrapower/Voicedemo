#!/usr/bin/env python3
"""GitHub research-loader isolation + grants.gov catalog POST allowlist. No live secrets."""
from __future__ import annotations
import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import web_fetch_v3 as W
import github_research_secret as G


class _Resp:
    def __init__(self, url, body, status=200, headers=None):
        self._url = url
        self.status = status
        self.code = status
        self.headers = headers or {"content-type": "application/json"}
        self._body = body if isinstance(body, bytes) else body.encode()
    def read(self, n=-1):
        b = self._body
        self._body = b""
        return b[:n] if n and n > 0 else b
    def close(self):
        pass
    def geturl(self):
        return self._url


class FourBlockerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.eg = self.root / "EGRESS.md"
        self.eg.write_text(
            "| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |\n"
            "| api.github.com | gh | yes | GITHUB_TOKEN | 1000 | issuer_claim | TEST | research |\n"
            "| other.test | x | yes | none | 1000 | attested | TEST | research |\n"
            "| api.grants.gov | g | yes | none | 1000 | attested | TEST | scout |\n"
            "| * | open | yes | none | 1000 | unverified | TEST | research,scout |\n",
            encoding="utf-8",
        )
        self.calls = []
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("GRID_GITHUB_RESEARCH_LOADED", None)
        G._LOADED = False

    def tearDown(self):
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("GRID_GITHUB_RESEARCH_LOADED", None)
        G._LOADED = False
        self.td.cleanup()

    def _opener(self, req, timeout=None):
        auth = req.headers.get("Authorization") or req.get_header("Authorization")
        self.calls.append({
            "url": req.full_url,
            "method": req.get_method(),
            "authorization": bool(auth),
            "auth_prefix": (auth or "")[:6],
        })
        if "api.github.com" in req.full_url:
            body = json.dumps({"items": [{"html_url": "https://github.com/ex/repo",
                                          "full_name": "ex/repo", "description": "d"}]})
            return _Resp(req.full_url, body)
        if req.full_url.endswith("/search2"):
            body = json.dumps({"errorcode": None, "data": {
                "hitCount": 1,
                "oppHits": [{"id": "12345", "title": "Health Research", "agency": "HHS",
                             "number": "AA-1", "oppStatus": "posted", "closeDate": "2026-12-01",
                             "openDate": "2026-01-01", "eligibilities": "unknown"}],
            }})
            return _Resp(req.full_url, body)
        if req.full_url.lower().endswith("fetchopportunity"):
            body = json.dumps({"data": {
                "opportunityTitle": "Health Research", "owningAgencyName": "HHS",
                "postedDate": "2026-01-01", "closeDate": "2026-12-01",
                "opportunityStatus": "posted", "eligibility": "public",
                "synopsis": "A posted opportunity synopsis.",
            }})
            return _Resp(req.full_url, body)
        if "/redirect-gh" in req.full_url:
            class Redir(_Resp):
                def __init__(self):
                    super().__init__(req.full_url, b"", 302, {"location": "https://other.test/page", "content-type": "text/plain"})
            return Redir()
        return _Resp(req.full_url, b"<html>nope</html>", 200, {"content-type": "text/html"})

    def test_github_without_loader_is_blocked_config(self):
        os.environ["GITHUB_TOKEN"] = "ambient-shell-token-SHOULD-NOT-BE-USED"
        sr = W.search("q", "research", n=1, max_pages=1, egress_path=str(self.eg),
                      opener=self._opener, _private_check=lambda h: False, providers=("github",))
        self.assertFalse(sr.get("ok"))
        st = (sr.get("attempts") or [{}])[0].get("status")
        self.assertEqual(st, "BLOCKED_CONFIG")
        self.assertEqual(self.calls, [])

    def test_github_loader_sends_only_allowlisted_url(self):
        p = self.root / "github_research.token"
        canary = "ghp_SYNTHETIC_CANARY_NOT_REAL_xx"
        p.write_text(canary + "\n", encoding="ascii")
        os.chmod(p, 0o600)
        loaded = G.load_into_environ(path=p)
        self.assertTrue(loaded["ok"])
        sr = W.search("q", "research", n=1, max_pages=1, egress_path=str(self.eg),
                      opener=self._opener, _private_check=lambda h: False, providers=("github",))
        self.assertTrue(sr.get("ok"))
        self.assertEqual(self.calls[0]["authorization"], True)
        self.assertTrue(self.calls[0]["url"].startswith("https://api.github.com/search/repositories"))
        blob = json.dumps(sr)
        self.assertNotIn(canary, blob)

    def test_github_cross_origin_redirect_drops_authorization(self):
        p = self.root / "github_research.token"
        p.write_text("ghp_SYNTHETIC_CANARY_NOT_REAL_yy\n", encoding="ascii")
        os.chmod(p, 0o600)
        G.load_into_environ(path=p)
        ok, why = W._github_auth_allowed("other.test", "/search/repositories", "GET")
        self.assertFalse(ok)
        ok, why = W._github_auth_allowed("api.github.com", "/user", "GET")
        self.assertFalse(ok)
        ok, why = W._github_auth_allowed("api.github.com", "/search/repositories", "POST")
        self.assertFalse(ok)

    def test_catalog_allowlist_and_parse(self):
        r = W.catalog_json_post(
            W.CATALOG_SEARCH2,
            {"rows": 10, "keyword": "health", "oppStatuses": "posted"},
            "scout", egress_path=str(self.eg),
            opener=self._opener, _private_check=lambda h: False,
        )
        self.assertTrue(r.get("ok"), r)
        parsed = W.normalize_opp_hits(r["json"], source_url=W.CATALOG_SEARCH2,
                                      fetched_at=1, original_query="health")
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["rows"][0]["opportunity_id"], "12345")
        bad = W.catalog_json_post("https://example.com/", {"rows": 10, "keyword": "x"},
                                  "scout", egress_path=str(self.eg),
                                  opener=self._opener, _private_check=lambda h: False)
        self.assertEqual(bad.get("status"), "DENIED")
        extra = W.catalog_json_post(W.CATALOG_SEARCH2, {"rows": 10, "keyword": "x", "worker": "cc"},
                                    "scout", egress_path=str(self.eg))
        self.assertEqual(extra.get("status"), "DENIED")

    def test_catalog_pending_exact_not_star(self):
        self.eg.write_text(
            "| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |\n"
            "| api.grants.gov | g | yes | none | 20 | attested | | scout |\n"
            "| * | open | yes | none | 1000 | unverified | TEST | research,scout |\n",
            encoding="utf-8",
        )
        r = W.catalog_json_post(
            W.CATALOG_SEARCH2,
            {"rows": 10, "keyword": "health", "oppStatuses": "posted"},
            "scout", egress_path=str(self.eg),
            opener=self._opener, _private_check=lambda h: False,
        )
        self.assertEqual(r.get("status"), "DENIED", r)
        self.assertEqual(r.get("matched_rule"), "api.grants.gov")
        self.assertEqual(self.calls, [])

    def test_github_ambient_loaded_flag_is_not_authorization(self):
        os.environ["GITHUB_TOKEN"] = "ambient-shell-token-SHOULD-NOT-BE-USED"
        os.environ["GRID_GITHUB_RESEARCH_LOADED"] = "1"
        sr = W.search("q", "research", n=1, max_pages=1, egress_path=str(self.eg),
                      opener=self._opener, _private_check=lambda h: False, providers=("github",))
        self.assertFalse(sr.get("ok"))
        st = (sr.get("attempts") or [{}])[0].get("status")
        self.assertEqual(st, "BLOCKED_CONFIG")
        self.assertEqual(self.calls, [])

    def test_loader_missing_file(self):
        r = G.load_into_environ(path=self.root / "nope")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "missing")
        self.assertNotIn("GITHUB_TOKEN", os.environ)
        self.assertFalse(G.loader_authorized())


if __name__ == "__main__":
    unittest.main(verbosity=2)
