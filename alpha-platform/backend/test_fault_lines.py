"""test_fault_lines.py — 断层位定版单测 (ALPHA_FACTORY_GLM V1.2)。"""
import json, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fault_lines as fl
import unittest


def _surf(flip=448.0, near=0.42, nxt=0.38, total_oi=5000):
    return {
        "gamma_flip": flip, "net_gex": -12.3,
        "per_strike_gex": {"445": 3.0, "448": 0.0, "450": -2.0},
        "per_strike_oi": {"445": {"call": 1200, "put": 300}, "450": {"call": 800, "put": 2000}},
        "total_oi": total_oi, "max_pain": 448.0,
        "near_next_iv": {"near": near, "next": nxt, "near_exp": "2026-09-19", "next_exp": "2026-10-17"},
        "n_contracts": 120, "oi_available": total_oi > 0, "date": "2026-08-19",
    }


class TestFaultLines(unittest.TestCase):
    def test_f1_gamma_flip_level(self):
        f1 = fl.compute_f1_gamma_flip(_surf(flip=448.0))
        self.assertEqual(f1["level"], 448.0)
        self.assertIsNotNone(f1["gex_slope"])

    def test_f2_oi_walls_floor(self):
        walls = fl.compute_f2_oi_walls(_surf(total_oi=5000))  # floor=250
        # call 1200,800 pass; put 2000,300 pass; call@450 oi=800>=250 ok
        self.assertTrue(any(w["K"] == 445.0 for w in walls["call"]))
        self.assertTrue(any(w["K"] == 450.0 for w in walls["put"]))
        # tiny OI below floor filtered
        walls2 = fl.compute_f2_oi_walls(_surf(total_oi=100000))  # floor=5000, all fail
        self.assertEqual(walls2["call"], [])
        self.assertEqual(walls2["put"], [])

    def test_f3_gap_edge(self):
        self.assertIsNone(fl.compute_f3_gap_edge(101.0, 100.0, 2.0))  # gap 1 < 3
        f3 = fl.compute_f3_gap_edge(105.0, 100.0, 2.0)  # gap 5 >= 3
        self.assertEqual(f3["upper"], 105.0)
        self.assertEqual(f3["lower"], 100.0)
        self.assertEqual(f3["direction"], "up")
        f3d = fl.compute_f3_gap_edge(95.0, 100.0, 2.0)
        self.assertEqual(f3d["direction"], "down")

    def test_f4_iv_inversion(self):
        self.assertFalse(fl.compute_f4_iv_inversion(_surf(near=0.3, nxt=0.4))["inverted"])
        self.assertTrue(fl.compute_f4_iv_inversion(_surf(near=0.5, nxt=0.4))["inverted"])
        self.assertIsNone(fl.compute_f4_iv_inversion({"near_next_iv": None}))

    def test_persist_load_fingerprint_reproducible(self):
        d = Path(tempfile.mkdtemp()) / "fl"
        sym = fl.build_fault_lines("SPY", "2026-08-21", 450.0, surface=_surf())
        fl.persist_fault_lines("2026-08-21", [sym], out_dir=d)
        loaded = fl.load_fault_lines("2026-08-21", out_dir=d)
        self.assertTrue(loaded["_fingerprint_ok"])
        self.assertTrue(fl.verify_reproducible("2026-08-21", out_dir=d))

    def test_merge_f3_updates_file(self):
        d = Path(tempfile.mkdtemp()) / "fl"
        sym = fl.build_fault_lines("SPY", "2026-08-21", 450.0, surface=_surf())
        fl.persist_fault_lines("2026-08-21", [sym], out_dir=d)
        ok = fl.merge_f3("2026-08-21", "SPY", fl.compute_f3_gap_edge(455.0, 450.0, 2.0), out_dir=d)
        self.assertTrue(ok)
        loaded = fl.load_fault_lines("2026-08-21", out_dir=d)
        self.assertIsNotNone(loaded["symbols"][0]["faults"]["F3_gap_edge"])
        self.assertTrue(loaded["_fingerprint_ok"])

    def test_update_f4_intraday(self):
        d = Path(tempfile.mkdtemp()) / "fl"
        sym = fl.build_fault_lines("SPY", "2026-08-21", 450.0, surface=_surf(near=0.3, nxt=0.4))
        fl.persist_fault_lines("2026-08-21", [sym], out_dir=d)
        new_f4 = fl.compute_f4_iv_inversion(_surf(near=0.5, nxt=0.4))
        ok = fl.update_f4_intraday("2026-08-21", "SPY", new_f4, out_dir=d)
        self.assertTrue(ok)
        loaded = fl.load_fault_lines("2026-08-21", out_dir=d)
        self.assertTrue(loaded["symbols"][0]["faults"]["F4_iv_inversion"]["inverted"])


if __name__ == "__main__":
    unittest.main()
