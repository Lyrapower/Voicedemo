"""Tests for FMP heat batch quotes."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import db
import fmp_heat_quotes


class FmpHeatQuotesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmpdir.name, "t.db")
        os.environ["PLATFORM_DB"] = self._db_path
        os.environ["PLATFORM_DB_DIRECT_WRITE"] = "1"
        db.DB_PATH = self._db_path

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("fmp_heat_quotes.httpx.get")
    def test_batch_store_and_crosscheck_stale(self, mock_get) -> None:
        mock_get.return_value.json.return_value = [
            {"symbol": "SPY", "price": 500.0, "volume": 1000, "timestamp": 1_700_000_000},
            {"symbol": "QQQ", "price": 400.0, "volume": 900, "timestamp": 1_700_000_000},
        ]
        mock_get.return_value.raise_for_status = lambda: None
        os.environ["FMP_API_KEY"] = "test-key"
        fmp_heat_quotes.FMP_API_KEY = "test-key"

        quotes, req_n, mode = fmp_heat_quotes.fetch_fmp_batch_quotes(["SPY", "QQQ"])
        self.assertEqual(len(quotes), 2)
        c = db.conn()
        try:
            n = fmp_heat_quotes.store_fmp_quotes_to_bars(c, quotes)
            self.assertEqual(n, 2)
            row = c.execute(
                "SELECT src, c FROM bars WHERE symbol='SPY' ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(row[0], "fmp_quote")
            self.assertEqual(row[1], 500.0)
        finally:
            c.close()

    @patch("fmp_heat_quotes._fetch_alpaca_iex")
    @patch("fmp_heat_quotes.fetch_fmp_batch_quotes")
    def test_pull_marks_stale_on_delta(self, mock_fmp, mock_alp) -> None:
        mock_fmp.return_value = (
            {"SPY": {"price": 100.0, "volume": 1, "quote_ts": 1_700_000_000}},
            1,
            "batch-quote",
        )
        mock_alp.return_value = {"SPY": {"last": 101.0, "bid": 100.9, "ask": 101.1}}
        c = db.conn()
        try:
            out = fmp_heat_quotes.pull_fmp_heat_quotes(c, ["SPY"])
            self.assertEqual(out["stored"], 1)
            self.assertEqual(out["crosscheck"]["stale_n"], 1)
            stale = c.execute("SELECT stale FROM heat_crosscheck WHERE symbol='SPY'").fetchone()[0]
            self.assertEqual(stale, 1)
            c.commit()
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
