"""Unit tests for seams wiring adapters (no network, temp db)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


os.environ["PLATFORM_DB_DIRECT_WRITE"] = "1"


class ScoutHeatExtractTests(unittest.TestCase):
    def test_movers_and_amc_rules(self) -> None:
        from scout_heat_adapter import extract_scout_noms

        doc = {
            "_engine": {
                "earnings_movers": [
                    {"symbol": "TEAM", "chg_pct": 31.0},
                    {"symbol": "SMALL", "chg_pct": 3.0},
                ],
                "amc_tonight": [
                    {"symbol": "AMAT", "chg5_pct": 5.0, "rsi14": 60.0, "chg_pct": 1.0},
                    {"symbol": "HOT", "chg5_pct": 20.0, "rsi14": 50.0},
                    {"symbol": "RSIH", "chg5_pct": 1.0, "rsi14": 80.0},
                ],
            }
        }
        noms = extract_scout_noms(doc)
        syms = [s for s, _, _ in noms]
        self.assertIn("TEAM", syms)
        self.assertNotIn("SMALL", syms)
        self.assertIn("AMAT", syms)
        self.assertNotIn("HOT", syms)
        self.assertNotIn("RSIH", syms)


class FactorSnapshotBuildTests(unittest.TestCase):
    def test_build_ranks_from_bars(self) -> None:
        import importlib
        import sqlite3
        import time

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        os.environ["PLATFORM_DB"] = tmp.name
        os.environ["WATCHLIST"] = "AAA,BBB,CCC"
        os.environ["SURFACE_DENY"] = ""
        import db
        import factor_truth
        import export_factor_snapshot as efs

        importlib.reload(db)
        importlib.reload(factor_truth)
        importlib.reload(efs)

        c = db.conn()
        factor_truth.ensure_schema(c)
        now = int(time.time())
        # 21 closes per sym with distinct trends
        for i, (sym, drift) in enumerate([("AAA", 0.01), ("BBB", 0.0), ("CCC", -0.01)]):
            for d in range(21):
                px = 100.0 * ((1 + drift) ** d)
                c.execute(
                    "INSERT OR REPLACE INTO daily_bars(ts, symbol, o, h, l, c, v) VALUES(?,?,?,?,?,?,?)",
                    (now - (21 - d) * 86400, sym, px, px, px, px, 1e6),
                )
        c.commit()
        ranks = efs.build_ranks(c, ["AAA", "BBB", "CCC"])
        c.close()
        os.unlink(tmp.name)
        self.assertEqual(len(ranks), 3)
        self.assertTrue(0.0 <= ranks["AAA"]["mom"] <= 1.0)
        self.assertIn("comp", ranks["AAA"])
        # AAA strongest mom → highest mom pct
        self.assertGreater(ranks["AAA"]["mom"], ranks["CCC"]["mom"])


if __name__ == "__main__":
    unittest.main()
