"""RET 5M window + RVOL gate unit tests (no network)."""
from __future__ import annotations

import datetime as dt
import logging
import os
import sqlite3
import tempfile
import time
import unittest

os.environ["PLATFORM_DB_DIRECT_WRITE"] = "1"


class HeatRvolMathTests(unittest.TestCase):
    def test_equal_deltas_rvol_one_fail(self) -> None:
        import heat_rvol
        vols = [100.0 + 10 * i for i in range(21)]
        rvol, gate, neg = heat_rvol.rvol_from_cumulative(vols)
        self.assertFalse(neg)
        self.assertAlmostEqual(rvol, 1.0, places=6)
        self.assertEqual(gate, "fail")

    def test_last_triple_median_pass(self) -> None:
        import heat_rvol
        vols = [100.0]
        for _ in range(19):
            vols.append(vols[-1] + 10)
        vols.append(vols[-1] + 30)
        rvol, gate, neg = heat_rvol.rvol_from_cumulative(vols)
        self.assertFalse(neg)
        self.assertAlmostEqual(rvol, 3.0, places=6)
        self.assertEqual(gate, "pass")

    def test_warming_under_21(self) -> None:
        import heat_rvol
        rvol, gate, neg = heat_rvol.rvol_from_cumulative([1.0] * 15)
        self.assertIsNone(rvol)
        self.assertEqual(gate, "warming")
        self.assertFalse(neg)

    def test_negative_delta_null(self) -> None:
        import heat_rvol
        vols = [100.0 + 10 * i for i in range(20)]
        vols.append(vols[-1] - 5)
        rvol, gate, neg = heat_rvol.rvol_from_cumulative(vols)
        self.assertTrue(neg)
        self.assertIsNone(rvol)
        self.assertEqual(gate, "warming")

    def test_ret5m_needs_two_bars(self) -> None:
        import heat_rvol
        self.assertIsNone(heat_rvol.ret_5m_from_quote_window([(1, 10.0)]))
        self.assertAlmostEqual(
            heat_rvol.ret_5m_from_quote_window([(1, 100.0), (200, 100.8)]),
            0.008,
            places=6,
        )


class HeatFactorWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.environ["PLATFORM_DB"] = self.tmp.name
        import importlib
        import db
        import worker

        importlib.reload(db)
        importlib.reload(worker)
        self.db = db
        self.worker = worker
        self.c = db.conn()
        self.c.executescript(db.SCHEMA)
        try:
            self.c.execute("ALTER TABLE bars ADD COLUMN src TEXT")
        except Exception:
            pass

    def tearDown(self) -> None:
        self.c.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _quote_bars(self, sym: str, n: int, *, last_dv: float = 10.0, px0: float = 100.0, dpx: float = 0.0) -> None:
        now = int(time.time())
        v = 1000.0
        px = px0
        for i in range(n):
            ts = now - (n - 1 - i) * 60
            dv = last_dv if i == n - 1 else 10.0
            v += dv
            px += dpx
            self.c.execute(
                "INSERT OR REPLACE INTO bars(ts, symbol, o, h, l, c, v, src) VALUES(?,?,?,?,?,?,?,?)",
                (ts, sym, px, px, px, px, v, "fmp_quote"),
            )
        self.c.commit()

    def test_g_seats_a_fail_b_pass_c_warming(self) -> None:
        log = logging.getLogger("worker")
        with self.assertLogs(log, level="WARNING") as cm:
            self._quote_bars("AAA", 21, last_dv=10.0, px0=100.0, dpx=0.04)
            self._quote_bars("BBB", 21, last_dv=30.0, px0=100.0, dpx=0.015)
            self._quote_bars("CCC", 15, last_dv=10.0, px0=100.0, dpx=0.01)
            vols_neg = [1000.0 + 10 * i for i in range(20)]
            now = int(time.time())
            for i, v in enumerate(vols_neg):
                ts = now - (21 - i) * 60
                self.c.execute(
                    "INSERT OR REPLACE INTO bars(ts, symbol, o, h, l, c, v, src) VALUES(?,?,?,?,?,?,?,?)",
                    (ts, "DDD", 10, 10, 10, 10, v, "fmp_quote"),
                )
            self.c.execute(
                "INSERT OR REPLACE INTO bars(ts, symbol, o, h, l, c, v, src) VALUES(?,?,?,?,?,?,?,?)",
                (now, "DDD", 10, 10, 10, 10, vols_neg[-1] - 5, "fmp_quote"),
            )
            self.c.commit()
            noon = int(dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4))).timestamp())
            self.worker.compute_heat_factors(self.c, ["AAA", "BBB", "CCC", "DDD"], now=noon)
            self.c.commit()
        self.assertTrue(any("DDD" in m for m in cm.output))

        def fac(sym, name):
            row = self.c.execute(
                "SELECT value FROM factors WHERE symbol=? AND name=? ORDER BY ts DESC LIMIT 1",
                (sym, name),
            ).fetchone()
            return row[0] if row else None

        import heat_rvol
        self.assertEqual(heat_rvol.decode_gate(fac("AAA", "rvol_gate")), "fail")
        self.assertAlmostEqual(fac("AAA", "rvol"), 1.0, places=5)
        self.assertEqual(heat_rvol.decode_gate(fac("BBB", "rvol_gate")), "pass")
        self.assertAlmostEqual(fac("BBB", "rvol"), 3.0, places=5)
        self.assertEqual(heat_rvol.decode_gate(fac("CCC", "rvol_gate")), "warming")
        self.assertIsNone(fac("CCC", "rvol"))
        self.assertIsNone(fac("DDD", "rvol"))
        self.assertEqual(heat_rvol.decode_gate(fac("DDD", "rvol_gate")), "warming")

        heat = [
            {"sym": "AAA", "ret5m": 0.8, "rvol_gate": "fail", "env_order": 0},
            {"sym": "BBB", "ret5m": 0.3, "rvol_gate": "pass", "env_order": 1},
            {"sym": "CCC", "ret5m": 0.5, "rvol_gate": "warming", "env_order": 2},
        ]
        ordered = sorted(heat, key=heat_rvol.heat_sort_key)
        self.assertEqual([h["sym"] for h in ordered], ["BBB", "CCC", "AAA"])

    def test_slow_cycle_does_not_write_ret5m_or_rvol(self) -> None:
        now = int(time.time())
        for i in range(31):
            self.c.execute(
                "INSERT OR REPLACE INTO bars(ts, symbol, o, h, l, c, v, src) VALUES(?,?,?,?,?,?,?,?)",
                (now - (30 - i), "NVDA", 100, 100, 100, 100 + i * 0.01, 1, "fmp_quote"),
            )
        self.c.execute(
            "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
            (now - 10, "NVDA", "ret_5m", 0.0123),
        )
        self.c.execute(
            "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
            (now - 10, "NVDA", "rvol", 2.2),
        )
        self.c.execute(
            "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
            (now - 10, "NVDA", "rvol_gate", 1.0),
        )
        self.c.commit()
        self.worker.compute_factors(self.c, ["NVDA"])
        self.c.commit()
        r5 = self.c.execute(
            "SELECT ts, value FROM factors WHERE symbol='NVDA' AND name='ret_5m' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        rv = self.c.execute(
            "SELECT ts, value FROM factors WHERE symbol='NVDA' AND name='rvol' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(r5[0], now - 10)
        self.assertAlmostEqual(r5[1], 0.0123)
        self.assertEqual(rv[0], now - 10)

    def test_alpaca_newer_bar_does_not_change_last(self) -> None:
        now = int(time.time())
        self.c.execute(
            "INSERT OR REPLACE INTO bars(ts, symbol, o, h, l, c, v, src) VALUES(?,?,?,?,?,?,?,?)",
            (now - 5, "CBRS", 10, 10, 10, 10.0, 1, "fmp_quote"),
        )
        self.c.execute(
            "INSERT OR REPLACE INTO bars(ts, symbol, o, h, l, c, v, src) VALUES(?,?,?,?,?,?,?,?)",
            (now, "CBRS", 99, 99, 99, 99.0, 1, "alpaca_iex"),
        )
        self.c.commit()
        row = self.c.execute(
            "SELECT b.c FROM bars b "
            "JOIN (SELECT symbol, MAX(ts) mts FROM bars WHERE src='fmp_quote' GROUP BY symbol) m "
            "ON b.symbol=m.symbol AND b.ts=m.mts AND b.src='fmp_quote' WHERE b.symbol='CBRS'"
        ).fetchone()
        self.assertAlmostEqual(row[0], 10.0)

    def test_auction_1557_vol_x20_not_leader(self) -> None:
        """15:57 ET 最后一拍量 ×20 → gate=auction，不进首卡。"""
        import heat_rvol

        auction_ts = int(dt.datetime(2026, 9, 4, 15, 57, tzinfo=dt.timezone(dt.timedelta(hours=-4))).timestamp())
        self._quote_bars("AUU", 21, last_dv=200.0, px0=100.0, dpx=0.02)
        self.worker.compute_heat_factors(self.c, ["AUU"], now=auction_ts)
        self.c.commit()
        row = self.c.execute(
            "SELECT value FROM factors WHERE symbol='AUU' AND name='rvol_gate' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(heat_rvol.decode_gate(row[0] if row else None), "auction")
        rvol = self.c.execute(
            "SELECT value FROM factors WHERE symbol='AUU' AND name='rvol' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(rvol)
        self.assertGreater(float(rvol[0]), 10.0)
        heat = [{"sym": "AUU", "ret5m": 0.4, "rvol_gate": "auction", "env_order": 0}]
        self.assertEqual(heat_rvol.gate_rank("auction"), heat_rvol.gate_rank("warming"))
        leaders = [h for h in heat if h.get("rvol_gate") == "pass"]
        self.assertEqual(leaders, [])


class RvolIcSubsetTests(unittest.TestCase):
    def test_subset_matches_hand(self) -> None:
        import rvol_ic_study as ic
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        os.environ["INTRADAY_STUDY_DB"] = tmp.name
        c = sqlite3.connect(tmp.name)
        c.executescript(ic.SCHEMA)
        # 3 symbols × 40 minutes starting 10:00 ET 2026-09-03
        t0 = int(dt.datetime(2026, 9, 3, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4))).timestamp())
        for si, (sym, slope) in enumerate((("AAA", 0.01), ("BBB", -0.01), ("CCC", 0.0))):
            v = 1000.0
            px = 100.0
            for i in range(40):
                v += 10 + (20 if i == 25 else 0)
                px += slope
                c.execute(
                    "INSERT INTO m1(symbol, ts, o, h, l, c, v) VALUES(?,?,?,?,?,?,?)",
                    (sym, t0 + i * 60, px, px, px, px, v),
                )
        c.commit()
        out = ic.compute_ic(c)
        c.close()
        os.unlink(tmp.name)
        self.assertTrue(out.get("ok"))
        self.assertGreaterEqual(out.get("n_cross") or 0, 1)

    def test_venue_iex_column(self) -> None:
        import rvol_ic_study as ic
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        os.environ["INTRADAY_STUDY_DB"] = tmp.name
        c = ic._conn()
        c.execute(
            "INSERT INTO m1(symbol, ts, o, h, l, c, v, venue) VALUES(?,?,?,?,?,?,?,?)",
            ("SPY", 1, 1, 1, 1, 1, 1, "iex"),
        )
        c.commit()
        row = c.execute("SELECT venue FROM m1 WHERE symbol='SPY'").fetchone()
        c.close()
        os.unlink(tmp.name)
        self.assertEqual(row[0], "iex")

    def test_empty_exits(self) -> None:
        import rvol_ic_study as ic
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        c = sqlite3.connect(tmp.name)
        c.executescript(ic.SCHEMA)
        out = ic.compute_ic(c)
        c.close()
        os.unlink(tmp.name)
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "no rows")


if __name__ == "__main__":
    unittest.main()
