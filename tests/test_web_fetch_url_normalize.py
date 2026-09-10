"""PKG_PRESTART_v1 step 1 — web.fetch URL normalize."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HR = ROOT / "harness_resident"
sys.path.insert(0, str(HR))
sys.path.insert(0, str(HR / "harness"))

from harness.url_normalize import normalize_url  # noqa: E402
from harness.web_fetch_v3 import fetch  # noqa: E402


class TestNormalizeUrl(unittest.TestCase):
    def test_space_in_query_encoded(self):
        raw = "https://api.grants.gov/v1/api/search2?keyword=clean energy&rows=10"
        url, why = normalize_url(raw)
        self.assertEqual(why, "ok")
        self.assertIsNotNone(url)
        self.assertIn("clean%20energy", url)
        self.assertNotIn("clean energy", url)

    def test_escaped_slashes_stripped(self):
        raw = '"https:\\/\\/api.grants.gov\\/v1\\/api\\/fetchOpportunity?oppId=359123\\""'
        url, why = normalize_url(raw)
        self.assertEqual(why, "ok")
        self.assertIsNotNone(url)
        self.assertNotIn("\\", url)
        self.assertTrue(url.startswith("https://api.grants.gov/v1/api/fetchOpportunity"))
        self.assertIn("oppId=359123", url)

    def test_no_scheme_or_broken_scheme(self):
        url, why = normalize_url("ht tp://x")
        self.assertIsNone(url)
        self.assertEqual(why, "no_scheme_or_host")
        url2, why2 = normalize_url("api.grants.gov/v1")
        self.assertIsNone(url2)
        self.assertEqual(why2, "no_scheme_or_host")


class TestFetchDeniedReceipt(unittest.TestCase):
    def test_denied_keeps_raw(self):
        raw = "ht tp://x"
        r = fetch(raw, "scout", db_path=None)
        self.assertEqual(r["status"], "DENIED")
        self.assertEqual(r["reason"], "INVALID_URL:no_scheme_or_host")
        self.assertEqual(r["raw"], raw)
        self.assertIsNone(r.get("url"))

    def test_denied_no_scheme(self):
        raw = "api.grants.gov/v1"
        r = fetch(raw, "scout", db_path=None)
        self.assertEqual(r["status"], "DENIED")
        self.assertEqual(r["reason"], "INVALID_URL:no_scheme_or_host")
        self.assertEqual(r["raw"], raw)


if __name__ == "__main__":
    unittest.main()
