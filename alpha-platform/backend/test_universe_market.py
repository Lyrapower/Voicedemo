"""Unit tests · universe market §0 fresh + loaders (no network)."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

os.environ["PLATFORM_DB_DIRECT_WRITE"] = "1"


class UniverseFreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.tmp_univ = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        json.dump(
            {
                "kind": "universe_market",
                "version": 1,
                "ts": 1e9,
                "n": 2,
                "symbols": ["MARA", "SMCI"],
                "rows": [
                    {"symbol": "MARA", "price": 15, "dollar_vol": 6e8, "market_cap": 4e9, "exchange": "NASDAQ"},
                    {"symbol": "SMCI", "price": 40, "dollar_vol": 8e8, "market_cap": 2e10, "exchange": "NASDAQ"},
                ],
            },
            self.tmp_univ,
        )
        self.tmp_univ.close()
        os.environ["PLATFORM_DB"] = self.tmp_db.name
        os.environ["UNIVERSE_MARKET_CACHE"] = self.tmp_univ.name
        import importlib
        import db
        import factor_truth

        importlib.reload(db)
        importlib.reload(factor_truth)
        self.ft = factor_truth
        self.c = db.conn()
        self.ft.ensure_schema(self.c)

    def tearDown(self) -> None:
        self.c.close()
        for p in (self.tmp_db.name, self.tmp_univ.name):
            try:
                os.unlink(p)
            except OSError:
                pass

    def _seed_bar(self, sym: str, day: dt.date, price: float = 100.0, vol: float = 2_000_000) -> None:
        ts = int(dt.datetime.combine(day, dt.time(0, 0), tzinfo=self.ft.ET).timestamp())
        self.c.execute(
            "INSERT OR REPLACE INTO daily_bars(ts,symbol,o,h,l,c,v) VALUES(?,?,?,?,?,?,?)",
            (ts, sym, price, price, price, price, vol),
        )
        self.c.commit()

    def test_0300_et_skip_all_sp500(self) -> None:
        monday = dt.date(2026, 8, 24)
        close_ts = int(dt.datetime.combine(monday, self.ft.RTH_CLOSE, tzinfo=self.ft.ET).timestamp()) + 3600
        for sym in ("AAPL", "MSFT", "NVDA"):
            self._seed_bar(sym, monday)
            self.ft._log_attempt(self.c, sym, got=True, now_ts=close_ts)
        t0300 = dt.datetime(2026, 8, 25, 3, 0, tzinfo=self.ft.ET)
        for sym in ("AAPL", "MSFT", "NVDA"):
            self.assertFalse(self.ft.needs_pull(self.c, sym, now=t0300)[0])
        with mock.patch("httpx.get") as hg:
            n = self.ft.pull_daily_bars(
                self.c, ["AAPL", "MSFT", "NVDA"], limit=2, skip_fresh=True
            )
            hg.assert_not_called()
        self.assertEqual(n, 0)

    def test_needs_pull_final_close_pass(self) -> None:
        monday = dt.date(2026, 8, 24)
        self._seed_bar("AAPL", monday)
        intraday = int(dt.datetime.combine(monday, dt.time(10, 0), tzinfo=self.ft.ET).timestamp())
        self.ft._log_attempt(self.c, "AAPL", got=True, now_ts=intraday)
        after_close = dt.datetime.combine(monday, self.ft.RTH_CLOSE, tzinfo=self.ft.ET) + dt.timedelta(
            seconds=self.ft.FINAL_PASS_AFTER_S + 600
        )
        need, why = self.ft.needs_pull(self.c, "AAPL", now=after_close)
        self.assertTrue(need)
        self.assertEqual(why, "final_close_pass")

    def test_load_universe_missing_no_sp500_fallback(self) -> None:
        missing = self.tmp_univ.name + ".gone"
        os.environ["UNIVERSE_MARKET_CACHE"] = missing
        import importlib
        importlib.reload(self.ft)
        with self.assertLogs("factor_truth", level="WARNING") as cm:
            doc = self.ft.load_universe_market(force=True)
        self.assertIsNone(doc)
        self.assertTrue(any("no sp500 fallback" in x for x in cm.output))
        os.environ["UNIVERSE_MARKET_CACHE"] = self.tmp_univ.name
        importlib.reload(self.ft)

    def test_movers_universe_tag(self) -> None:
        tue = dt.date(2026, 8, 25)
        mon = dt.date(2026, 8, 24)
        for sym, px, vol in (("AAPL", 200, 2_000_000), ("MARA", 15, 8_000_000)):
            for i in range(20):
                d = mon - dt.timedelta(days=i)
                self._seed_bar(sym, d, px, vol)
            self._seed_bar(sym, mon, px, vol)
            self._seed_bar(sym, tue, px * 1.05, vol)
        payload = self.ft._build_mover_rows(
            self.c, ["AAPL", "MARA"], set(), {"AAPL"}, {"MARA", "SMCI"}, readonly=True
        )
        tags = {r["sym"]: r["universe"] for r in (payload.get("gainers") or []) + (payload.get("losers") or [])}
        self.assertEqual(tags.get("AAPL"), "sp500")
        self.assertEqual(tags.get("MARA"), "market")


class Adv20FloorTests(unittest.TestCase):
    def test_ignores_quote_volume_uses_adv20(self) -> None:
        import build_universe as bu

        rows = [
            {
                "symbol": "AAA",
                "price": 20,
                "volume": 0,
                "marketCap": 1e9,
                "isEtf": False,
                "isFund": False,
                "isActivelyTrading": True,
                "exchangeShortName": "NASDAQ",
            },
            {
                "symbol": "BBB",
                "price": 20,
                "volume": 9e12,
                "marketCap": 1e9,
                "isEtf": False,
                "isFund": False,
                "isActivelyTrading": True,
                "exchangeShortName": "NASDAQ",
            },
        ]
        adv = {"AAA": (6e7, 1000), "BBB": (1e6, 999)}
        out, dropped = bu.build(rows, adv20=adv)
        self.assertEqual([r["symbol"] for r in out], ["AAA"])
        self.assertEqual(out[0]["volume"], 1000)
        self.assertEqual(out[0]["dollar_vol"], 60000000)
        self.assertEqual(dropped["dollar_vol"], 1)


class RefreshIfStaleTests(unittest.TestCase):
    def test_skips_fresh_file(self) -> None:
        import build_universe as bu

        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        json.dump({"kind": "universe_market", "ts": time.time(), "n": 1}, tmp)
        tmp.close()
        try:
            with mock.patch.object(bu, "run_build") as rb:
                self.assertEqual(bu.refresh_if_stale(max_age_h=24.0, out=tmp.name), "skipped")
                rb.assert_not_called()
        finally:
            os.unlink(tmp.name)

    def test_rebuilds_stale_and_does_not_sys_exit(self) -> None:
        import build_universe as bu

        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        json.dump({"kind": "universe_market", "ts": 1.0, "n": 1}, tmp)
        tmp.close()
        try:
            with mock.patch.object(bu, "run_build", return_value={"n": 9}):
                self.assertEqual(bu.refresh_if_stale(max_age_h=24.0, out=tmp.name), "refreshed")
            with mock.patch.object(bu, "run_build", side_effect=bu.UniverseError("no")):
                self.assertEqual(bu.refresh_if_stale(max_age_h=24.0, out=tmp.name), "failed")
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
