import unittest
from harness.web_fetch_normalize import normalize_url as n

class NormalizeTests(unittest.TestCase):
    def test_space(self):
        self.assertEqual(n('https://x.org/?q=a  b')[0], 'https://x.org/?q=a%20%20b')
    def test_json_escapes(self):
        self.assertEqual(n('"https:\\/\\/api.grants.gov\\/v1\\/api\\/fetchOpportunity?oppId=359123\\""')[0], 'https://api.grants.gov/v1/api/fetchOpportunity?oppId=359123')
    def test_bad_scheme(self):
        for v in ('ht tp://x', 'x.org', 'file:///a', '//x.org'):
            with self.subTest(v=v): self.assertIsNone(n(v)[0])
    def test_idempotent(self):
        v = n('https://例子.测试/a b?q=x%2Fy+z#frag')[0]
        self.assertEqual(n(v)[0], v)
    def test_control(self):
        for v in ('https://x.org/a\nb', 'https://x.org/?q=%0d', 'https://x.org/\t'):
            with self.subTest(v=v): self.assertIsNone(n(v)[0])
    def test_authority(self):
        for v in ('https://user:pw@x.org', 'https://x.org:99999', 'https://[a', 'https://bad host/', 'https://x.org:', 'https://%31%32%37.0.0.1'):
            with self.subTest(v=v): self.assertIsNone(n(v)[0])
    def test_bad_type(self):
        for v in (None, 3, {}, ''): self.assertIsNone(n(v)[0])
    def test_bad_escape(self):
        for v in ('https://x.org/%ZZ', 'https://x.org/a\\b'): self.assertIsNone(n(v)[0])
    def test_query_preserved(self):
        self.assertEqual(n('https://x.org/?a=1&a=2&q=a+b%20c&sig=x%2fy')[0], 'https://x.org/?a=1&a=2&q=a+b%20c&sig=x%2fy')
    def test_ipv6_and_normalization_not_ssrf_gate(self):
        self.assertEqual(n('http://[::1]:8080/a')[0], 'http://[::1]:8080/a')
