import unittest
from datetime import datetime, timezone

from bridge_kit import theta_probe as tp

EXPS = '{"response":["20260911","20260918","20261016"]}'
STRIKES = '{"response":[95.0,100.0,105.0,110.0]}'


def make_get(mdds="CONNECTED", exps=(200, EXPS), strikes=(200, STRIKES), quote=(472, "")):
    calls = []

    def get(url):
        calls.append(url)
        if url == tp.EP_MDDS:
            return 200, mdds
        if "/option/list/expirations" in url:
            return exps
        if "/option/list/strikes" in url:
            return strikes
        if "/option/snapshot/quote" in url:
            return quote
        return 404, ""
    get.calls = calls
    return get


# 2026-09-10 22:00 PDT = 2026-09-11 01:00 ET(午夜 ET 之后,快照缓存已清)
AFTER_MIDNIGHT_ET = datetime(2026, 9, 11, 5, 0, tzinfo=timezone.utc)
# 2026-09-11 13:00 ET(RTH 内)
IN_RTH = datetime(2026, 9, 11, 17, 0, tzinfo=timezone.utc)


class T(unittest.TestCase):
    def test_execution_v2_style_strike_rejected_before_any_http(self):
        get = make_get()
        r = tp.classify_472("SPY", "20260918", "100000", "call", get)
        self.assertEqual(r["verdict"], "PARAM_STRIKE_FORMAT_V2")
        self.assertEqual(get.calls, [])

    def test_execution_terminal_disconnected(self):
        get = make_get(mdds="DISCONNECTED")
        r = tp.classify_472("SPY", "20260918", "100", "call", get)
        self.assertEqual(r["verdict"], "TERMINAL_NOT_CONNECTED")

    def test_execution_expiration_not_listed(self):
        get = make_get()
        r = tp.classify_472("SPY", "2026-09-12", "100", "call", get)
        self.assertEqual(r["verdict"], "PARAM_EXPIRATION_NOT_LISTED")
        self.assertEqual(r["evidence"]["exp_wanted"], "20260912")

    def test_execution_strike_not_listed(self):
        get = make_get()
        r = tp.classify_472("SPY", "20260918", "102.5", "call", get)
        self.assertEqual(r["verdict"], "PARAM_STRIKE_NOT_LISTED")

    def test_execution_after_midnight_et_is_time_window(self):
        get = make_get()
        r = tp.classify_472("SPY", "20260918", "100", "call", get, now_utc=AFTER_MIDNIGHT_ET)
        self.assertEqual(r["verdict"], "TIME_WINDOW_SNAPSHOT_EMPTY")
        self.assertTrue(r["evidence"]["now_et"].startswith("2026-09-11T01:00"))

    def test_execution_in_rth_still_472_escalates(self):
        get = make_get()
        r = tp.classify_472("SPY", "20260918", "100", "call", get, now_utc=IN_RTH)
        self.assertEqual(r["verdict"], "NO_DATA_IN_RTH_UNEXPLAINED")

    def test_quote_ok_now(self):
        get = make_get(quote=(200, '{"bid":1.2,"ask":1.3}'))
        r = tp.classify_472("SPY", "20260918", "100", "call", get, now_utc=IN_RTH)
        self.assertEqual(r["verdict"], "QUOTE_OK_NOW")
        # 打的 URL 是 v3 口径:美元三位小数、right=call
        self.assertTrue(get.calls[-1].endswith("expiration=20260918&strike=100.000&right=call&format=json"))
        self.assertTrue(get.calls[-1].startswith("http://127.0.0.1:25503/v3/option/snapshot/quote"))

    def test_execution_permission_471_named_not_swallowed(self):
        get = make_get(quote=(471, ""))
        r = tp.classify_472("SPY", "20260918", "100", "call", get, now_utc=IN_RTH)
        self.assertEqual(r["verdict"], "QUOTE_PERMISSION")

    def test_snapshot_window(self):
        self.assertFalse(tp.snapshot_window_open(datetime(2026, 9, 12, 12, 0)))  # 周六
        self.assertFalse(tp.snapshot_window_open(datetime(2026, 9, 11, 1, 0)))   # 午夜后
        self.assertTrue(tp.snapshot_window_open(datetime(2026, 9, 11, 13, 0)))


if __name__ == "__main__":
    unittest.main()
