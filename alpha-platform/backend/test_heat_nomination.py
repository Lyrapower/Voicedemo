"""Deterministic heat nomination unit tests (no LLM, no network)."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

os.environ["PLATFORM_DB_DIRECT_WRITE"] = "1"


class HeatNominationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.environ["PLATFORM_DB"] = self.tmp.name
        os.environ["WATCHLIST"] = "NVDA,PLTR,AMZN,NOW"
        os.environ["SURFACE_DENY"] = "TSLA,GOOGL"
        os.environ["HEAT_SCAN_NOMINATION_CAP"] = "8"
        import importlib
        import db
        import heat_nomination

        importlib.reload(db)
        importlib.reload(heat_nomination)
        self.db = db
        self.hn = heat_nomination

    def tearDown(self) -> None:
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_cap_and_overflow(self) -> None:
        c = self.db.conn()
        self.hn.ensure_schema(c)
        today = self.hn._today_et().isoformat()
        # inject 12 nominations with descending scores
        for i in range(12):
            sym = f"S{i:02d}"
            c.execute(
                "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
                "VALUES(?,?,?,?,?,?)",
                (sym, "scan", today, today, 100 - i, "{}"),
            )
        c.commit()
        heat = self.hn._pack_heat(c, refresh=False)
        c.close()
        scan_seats = [s for s, src in heat["sources"].items() if src in ("scan", "bfs", "movers")]
        self.assertLessEqual(len(scan_seats), 8)
        self.assertEqual(heat["nomination"]["overflow_n"], 12 - len(scan_seats))
        for s in self.db.BASE_WATCHLIST:
            if s not in self.db.SURFACE_DENY:
                self.assertEqual(heat["sources"].get(s), "watchlist")

    def test_deny_veto_only(self) -> None:
        c = self.db.conn()
        self.hn.ensure_schema(c)
        today = self.hn._today_et().isoformat()
        c.execute(
            "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
            "VALUES(?,?,?,?,?,?)",
            ("TSLA", "scan", today, today, 999, "{}"),
        )
        c.commit()
        heat = self.hn._pack_heat(c, refresh=False)
        c.close()
        self.assertNotIn("TSLA", heat["watchlist"])

    def test_aehr_surface_deny(self) -> None:
        os.environ["SURFACE_DENY"] = "TSLA,GOOGL,AEHR"
        import importlib

        importlib.reload(self.db)
        importlib.reload(self.hn)
        c = self.db.conn()
        self.hn.ensure_schema(c)
        today = self.hn._today_et().isoformat()
        c.execute(
            "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
            "VALUES(?,?,?,?,?,?)",
            ("AEHR", "scan", today, today, 999, "{}"),
        )
        c.commit()
        heat = self.hn._pack_heat(c, refresh=False)
        c.close()
        self.assertNotIn("AEHR", heat["watchlist"])
        os.environ["SURFACE_DENY"] = "TSLA,GOOGL"
        importlib.reload(self.db)
        importlib.reload(self.hn)

    def test_empty_watchlist_no_resident_seats(self) -> None:
        os.environ["WATCHLIST"] = ""
        import importlib
        importlib.reload(self.db)
        importlib.reload(self.hn)
        self.assertEqual(self.db.BASE_WATCHLIST, [])
        tuesday = dt.date(2026, 8, 25)
        c = self.db.conn()
        self.hn.ensure_schema(c)
        c.execute(
            "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
            "VALUES(?,?,?,?,?,?)",
            ("SMCI", "scan", tuesday.isoformat(), tuesday.isoformat(), 80, "{}"),
        )
        c.commit()
        with mock.patch.object(self.hn, "_today_et", return_value=tuesday):
            heat = self.hn._pack_heat(c, refresh=False)
        c.close()
        self.assertNotIn("NVDA", heat["watchlist"])
        self.assertNotIn("PLTR", heat["watchlist"])
        self.assertNotIn("AMZN", heat["watchlist"])
        self.assertNotIn("NOW", heat["watchlist"])
        self.assertEqual(heat["watchlist"], ["SMCI"])
        self.assertIn(heat["sources"].get("SMCI"), ("bfs", "scan"))
        self.assertFalse(any(src == "watchlist" for src in heat["sources"].values()))
        os.environ["WATCHLIST"] = "NVDA,PLTR,AMZN,NOW"
        importlib.reload(self.db)
        importlib.reload(self.hn)

    def test_t3_scan_not_on_heat(self) -> None:
        """Friday BFS last_on cannot occupy Tuesday scan seats or overflow."""
        tuesday = dt.date(2026, 8, 25)
        friday = dt.date(2026, 8, 21)
        c = self.db.conn()
        self.hn.ensure_schema(c)
        c.execute(
            "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
            "VALUES(?,?,?,?,?,?)",
            ("INTC", "scan", friday.isoformat(), friday.isoformat(), 90, "{}"),
        )
        c.execute(
            "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
            "VALUES(?,?,?,?,?,?)",
            ("SMCI", "scan", tuesday.isoformat(), tuesday.isoformat(), 80, "{}"),
        )
        c.commit()
        with mock.patch.object(self.hn, "_today_et", return_value=tuesday):
            heat = self.hn._pack_heat(c, refresh=False)
        c.close()
        self.assertNotIn("INTC", heat["watchlist"])
        self.assertFalse(any(x.get("symbol") == "INTC" for x in heat["scan_candidates"]))
        self.assertIn("SMCI", heat["watchlist"])
        self.assertIn(heat["sources"].get("SMCI"), ("bfs", "scan"))
        for s in ("NVDA", "PLTR", "AMZN", "NOW"):
            self.assertEqual(heat["sources"].get(s), "watchlist")

    def test_refresh_demotes_t3(self) -> None:
        tuesday = dt.date(2026, 8, 25)
        friday = dt.date(2026, 8, 21)
        c = self.db.conn()
        self.hn.ensure_schema(c)
        c.execute(
            "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
            "VALUES(?,?,?,?,?,?)",
            ("INTC", "scan", friday.isoformat(), friday.isoformat(), 90, "{}"),
        )
        c.commit()
        with mock.patch.object(self.hn, "_today_et", return_value=tuesday), mock.patch.object(
            self.hn, "_collect_bfs_bucket", return_value=[]
        ), mock.patch.object(self.hn, "_collect_movers_bucket", return_value=[]):
            nom = self.hn.refresh_nominations(c)
        left = c.execute("SELECT symbol FROM heat_nominations").fetchall()
        c.close()
        self.assertEqual(left, [])
        self.assertEqual(nom["seats"], [])
        self.assertEqual(nom["asof"], "2026-08-25")

    def test_today_stamp_without_today_rank_dropped(self) -> None:
        """last_on=today is not enough if this tick did not re-rank the name."""
        tuesday = dt.date(2026, 8, 25)
        c = self.db.conn()
        self.hn.ensure_schema(c)
        c.execute(
            "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
            "VALUES(?,?,?,?,?,?)",
            ("EXPE", "scan", tuesday.isoformat(), tuesday.isoformat(), 99, "{}"),
        )
        c.commit()
        with mock.patch.object(self.hn, "_today_et", return_value=tuesday), mock.patch.object(
            self.hn, "_collect_bfs_bucket", return_value=[]
        ), mock.patch.object(self.hn, "_collect_movers_bucket", return_value=[]):
            nom = self.hn.refresh_nominations(c)
        left = c.execute("SELECT symbol FROM heat_nominations").fetchall()
        c.close()
        self.assertEqual(left, [])
        self.assertEqual(nom["seats"], [])

    def test_movers_not_same_day_dropped(self) -> None:
        tuesday = dt.date(2026, 8, 25)
        monday_midnight = int(dt.datetime(2026, 8, 24, tzinfo=self.hn._ET).timestamp())
        movers = {
            "asof_ts": monday_midnight,
            "gainers": [{"symbol": "EXPE", "ret1d": 5.4, "asof_ts": monday_midnight}],
        }
        out = self.hn._same_day_movers(movers, tuesday)
        self.assertEqual(out.get("gainers"), [])

    def test_bfs_movers_buckets(self) -> None:
        """H 处决: BFS 80/70/60/50 + movers 12/11/10/9/8/7 → 4+4 席, overflow 8/7."""
        bfs = [("B1", 80, "bfs"), ("B2", 70, "bfs"), ("B3", 60, "bfs"), ("B4", 50, "bfs")]
        movers = [
            ("M12", 12, "movers"), ("M11", 11, "movers"), ("M10", 10, "movers"),
            ("M9", 9, "movers"), ("M8", 8, "movers"), ("M7", 7, "movers"),
        ]
        seats, overflow = self.hn.allocate_heat_seats(bfs, movers)
        self.assertEqual([s for s, _, w in seats if w == "bfs"], ["B1", "B2", "B3", "B4"])
        self.assertEqual([s for s, _, w in seats if w == "movers"], ["M12", "M11", "M10", "M9"])
        self.assertEqual([(s, sc) for s, sc, _ in overflow], [("M8", 8), ("M7", 7)])


class FactorDedupTests(unittest.TestCase):
    def test_fingerprint_stable(self) -> None:
        import factor_dedup

        a = "def factor(df):\n    return df['c'].pct_change()\n"
        b = "def factor(df):\n  return df['c'].pct_change()  # comment\n"
        self.assertEqual(factor_dedup.factor_fingerprint(a), factor_dedup.factor_fingerprint(b))

    def test_missed_movers(self) -> None:
        from missed_movers import compute_missed_movers

        gainers = [{"sym": f"G{i}", "ret1d": 10 - i} for i in range(20)]
        out = compute_missed_movers(gainers, {"G0", "G1"}, {"NVDA"})
        self.assertEqual(out["count"], 18)
        self.assertEqual(out["level"], "amber")


if __name__ == "__main__":
    unittest.main()
