"""test_heat_h.py — H 公式 + 推送冷却/cross/stale/F4 加成单测 (ALPHA_FACTORY_GLM V1.2)。"""
import os, sys, sqlite3, tempfile, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heat_h as h
import heat_anomaly_bark as hb
import unittest


class TestHeatFormula(unittest.TestCase):
    def test_h_weights_sum_to_100(self):
        # all components = 1.0 → H = 100
        r = h.compute_heat("X", "F1_gamma_flip", 100.0, price=100.0, spot=100.0,
                           ret_15m=0.02, vol_x20=2.0, g_percentile=1.0, f4_inverted=False, crossed=False)
        self.assertAlmostEqual(r["H"], 100.0, places=1)

    def test_h_all_zero(self):
        r = h.compute_heat("X", "F1_gamma_flip", 100.0, price=200.0, spot=100.0,
                           ret_15m=0.0, vol_x20=0.0, g_percentile=0.0, f4_inverted=False, crossed=False)
        self.assertAlmostEqual(r["H"], 0.0, places=1)

    def test_cross_event_floor(self):
        r = h.compute_heat("X", "F1_gamma_flip", 100.0, price=100.5, spot=100.0,
                           ret_15m=0.001, vol_x20=1.8, g_percentile=0.5, f4_inverted=False, crossed=True)
        self.assertTrue(r["cross_event"])
        self.assertGreaterEqual(r["H"], 85.0)

    def test_cross_no_volume_no_event(self):
        r = h.compute_heat("X", "F1_gamma_flip", 100.0, price=100.5, spot=100.0,
                           ret_15m=0.001, vol_x20=1.0, g_percentile=0.5, f4_inverted=False, crossed=True)
        self.assertFalse(r["cross_event"])  # vol_x20 < 1.5

    def test_f4_inversion_boost_g(self):
        r_no = h.compute_heat("X", "F1_gamma_flip", 100.0, price=100.0, spot=100.0,
                              ret_15m=0.0, vol_x20=0.0, g_percentile=0.5, f4_inverted=False, crossed=False)
        r_yes = h.compute_heat("X", "F1_gamma_flip", 100.0, price=100.0, spot=100.0,
                               ret_15m=0.0, vol_x20=0.0, g_percentile=0.5, f4_inverted=True, crossed=False)
        self.assertGreater(r_yes["G"], r_no["G"])
        self.assertAlmostEqual(r_yes["G"], 0.5 + 0.5 * 0.25, places=3)

    def test_f4_state_d(self):
        r_inv = h.compute_heat("X", "F4_iv_inversion", None, price=100.0, spot=100.0,
                               ret_15m=0.0, vol_x20=1.0, g_percentile=None, f4_inverted=True, crossed=False)
        r_norm = h.compute_heat("X", "F4_iv_inversion", None, price=100.0, spot=100.0,
                                ret_15m=0.0, vol_x20=1.0, g_percentile=None, f4_inverted=False, crossed=False)
        self.assertEqual(r_inv["D"], 1.0)
        self.assertEqual(r_norm["D"], 0.0)
        self.assertEqual(r_inv["G"], 1.0)

    def test_f3_fixed_g(self):
        r = h.compute_heat("X", "F3_gap_edge", 105.0, price=104.5, spot=100.0,
                           ret_15m=0.0, vol_x20=0.0, g_percentile=0.9, f4_inverted=False, crossed=False)
        self.assertEqual(r["G"], 0.5)  # F3 ignores g_percentile


class TestHeatBark(unittest.TestCase):
    def setUp(self):
        # mock bark to avoid real push
        hb._bark_url = lambda: ""
        hb.send_bark = lambda title, body, group="heat-faultline": "已推送"
        self.d = Path(tempfile.mkdtemp()) / "t.db"
        self.c = sqlite3.connect(str(self.d))

    def tearDown(self):
        self.c.close()

    def test_stale_blocks_push(self):
        now = time.time()
        heat = h.compute_heat("SPY", "F1_gamma_flip", 448.0, price=447.5, spot=448.0,
                              ret_15m=0.004, vol_x20=2.0, g_percentile=0.9, f4_inverted=False, crossed=False)
        r = hb.push_heat(heat, data_asof_ts=now - 400, conn=self.c)
        self.assertIn("stale", r)

    def test_cooldown_same_value(self):
        now = time.time()
        heat = h.compute_heat("SPY", "F1_gamma_flip", 448.0, price=447.5, spot=448.0,
                              ret_15m=0.004, vol_x20=2.0, g_percentile=0.9, f4_inverted=False, crossed=False)
        r1 = hb.push_heat(heat, data_asof_ts=now, conn=self.c)
        self.assertIn("已推送", r1)
        r2 = hb.push_heat(heat, data_asof_ts=now, conn=self.c)
        self.assertIn("冷却", r2)

    def test_cross_push_separate_cooldown(self):
        now = time.time()
        heat = h.compute_heat("SPY", "F1_gamma_flip", 448.0, price=448.2, spot=448.0,
                              ret_15m=0.003, vol_x20=1.8, g_percentile=0.7, f4_inverted=True, crossed=True)
        r = hb.push_heat(heat, data_asof_ts=now, conn=self.c)
        self.assertIn("cross:已推送", r)

    def test_f4_inversion_occur_push(self):
        now = time.time()
        f4 = {"inverted": True, "near_iv": 0.5, "next_iv": 0.4,
              "near_exp": "2026-09-19", "next_exp": "2026-10-17", "ratio": 1.25}
        r = hb.push_iv_inversion("SPY", f4, prev_f4_state={"inverted": False, "ratio": 0.95},
                                  data_asof_ts=now, conn=self.c)
        self.assertIn("已推送", r)

    def test_f4_no_change_no_push(self):
        now = time.time()
        f4 = {"inverted": True, "near_iv": 0.5, "next_iv": 0.4,
              "near_exp": "2026-09-19", "next_exp": "2026-10-17", "ratio": 1.25}
        r = hb.push_iv_inversion("SPY", f4, prev_f4_state=f4, data_asof_ts=now, conn=self.c)
        self.assertIn("无状态变化", r)

    def test_cooldown_persists_across_restarts(self):
        now = time.time()
        heat = h.compute_heat("SPY", "F1_gamma_flip", 448.0, price=447.5, spot=448.0,
                              ret_15m=0.004, vol_x20=2.0, g_percentile=0.9, f4_inverted=False, crossed=False) if False else \
            h.compute_heat("SPY", "F1_gamma_flip", 448.0, price=447.5, spot=448.0,
                           ret_15m=0.004, vol_x20=2.0, g_percentile=0.9, f4_inverted=False, crossed=False)
        hb.push_heat(heat, data_asof_ts=now, conn=self.c)
        self.c.close()
        c2 = sqlite3.connect(str(self.d))
        r = hb.push_heat(heat, data_asof_ts=now, conn=c2)
        self.assertIn("冷却", r)
        c2.close()


if __name__ == "__main__":
    unittest.main()
