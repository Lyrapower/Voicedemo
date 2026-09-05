#!/usr/bin/env python3
"""Tests for premarket A/B — isolation, divergence, journal separation."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from premarket_ab_divergence import find_divergences, format_divergence_push, is_divergent
from premarket_ab_isolation import assert_grid_prompt_isolated, assert_sonnet_prompt_isolated
from premarket_ab_journal import append_premarket_journal, reconcile_chain


class TestPremarketAbIsolation(unittest.TestCase):
    def test_grid_rejects_sonnet_leak(self) -> None:
        with self.assertRaises(ValueError):
            assert_grid_prompt_isolated("prior aether_premarket_sonnet output: NVDA 多")

    def test_sonnet_rejects_grid_leak(self) -> None:
        with self.assertRaises(ValueError):
            assert_sonnet_prompt_isolated("Grid lane said NVDA 多")

    def test_clean_pool_context_ok(self) -> None:
        assert_grid_prompt_isolated("Pool universe (18): NVDA, AMD\nOvernight context")
        assert_sonnet_prompt_isolated("Pool universe (18): NVDA, AMD\nOvernight context")


class TestPremarketAbDivergence(unittest.TestCase):
    def test_dir_divergence(self) -> None:
        g = {"sym": "NVDA", "dir": 1, "value": "多 · [高置信]"}
        s = {"sym": "NVDA", "dir": -1, "value": "空 · [高置信]"}
        self.assertTrue(is_divergent(g, s))

    def test_confidence_gap_divergence(self) -> None:
        g = {"sym": "AMD", "dir": 1, "value": "多 · [高置信]"}
        s = {"sym": "AMD", "dir": 1, "value": "多 · [观察]"}
        self.assertTrue(is_divergent(g, s))

    def test_aligned_not_divergent(self) -> None:
        g = {"sym": "TSLA", "dir": 1, "value": "多 · [高置信]"}
        s = {"sym": "TSLA", "dir": 1, "value": "多 · [试探性]"}
        self.assertFalse(is_divergent(g, s))

    def test_push_format_non_empty(self) -> None:
        divs = find_divergences(
            [{"sym": "NVDA", "dir": 1, "value": "多 · [高置信]"}],
            [{"sym": "NVDA", "dir": 0, "value": "观察 · [观察]"}],
        )
        msg = format_divergence_push("2026-07-09", divs)
        self.assertIn("盘前 A/B 分歧", msg)
        self.assertIn("NVDA", msg)


class TestPremarketAbJournal(unittest.TestCase):
    def test_journals_physically_separate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            grid_p = root / "journal_grid.jsonl"
            sonnet_p = root / "journal_sonnet.jsonl"
            with mock.patch("premarket_ab_journal.JOURNAL_DIR", root), mock.patch(
                "premarket_ab_journal.JOURNAL_GRID", grid_p
            ), mock.patch("premarket_ab_journal.JOURNAL_SONNET", sonnet_p):
                items = [{"sym": "NVDA", "dir": 1, "confidence": "高置信", "value": "多", "note": "x"}]
                append_premarket_journal(chain="grid", trade_date="2026-07-09", items=items)
                append_premarket_journal(chain="sonnet", trade_date="2026-07-09", items=items)
                self.assertTrue(grid_p.is_file())
                self.assertTrue(sonnet_p.is_file())
                grid_rows = [json.loads(l) for l in grid_p.read_text().splitlines()]
                sonnet_rows = [json.loads(l) for l in sonnet_p.read_text().splitlines()]
                self.assertEqual(grid_rows[0]["chain"], "grid")
                self.assertEqual(sonnet_rows[0]["chain"], "sonnet")
                with mock.patch("premarket_ab_journal.STATS_GRID", root / "stats_grid.json"), mock.patch(
                    "premarket_ab_journal.STATS_SONNET", root / "stats_sonnet.json"
                ):
                    g = reconcile_chain("grid", "2026-07-09", outcomes={"NVDA": 0.02})
                    s = reconcile_chain("sonnet", "2026-07-09", outcomes={"NVDA": 0.02})
                self.assertEqual(g["wins"], 1)
                self.assertEqual(s["wins"], 1)
                self.assertNotEqual(g.get("chain"), s.get("chain"))


class TestPremarketAbReturns(unittest.TestCase):
    def test_chain_signed_return(self) -> None:
        items = [{"sym": "NVDA", "dir": 1}, {"sym": "TSLA", "dir": -1}]
        outcomes = {"NVDA": 0.02, "TSLA": 0.01}
        ret = __import__("premarket_ab_returns").chain_signed_return_pct(items, outcomes)
        assert ret is not None
        self.assertAlmostEqual(ret, 0.005, places=4)

    def test_observe_excluded_from_return(self) -> None:
        items = [{"sym": "NVDA", "dir": 1}, {"sym": "BABA", "dir": 0}]
        outcomes = {"NVDA": 0.02, "BABA": 0.05}
        ret = __import__("premarket_ab_returns").chain_signed_return_pct(items, outcomes)
        assert ret is not None
        self.assertAlmostEqual(ret, 0.02, places=4)

    def test_rolling_win_rate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stats = {
                "2026-07-15": {"wins": 2, "losses": 1, "return_pct": 0.01},
                "2026-07-16": {"wins": 1, "losses": 0, "return_pct": 0.02},
                "2026-07-14": {"wins": 9, "losses": 0, "warmup": True, "ab_void": True},
            }
            gp = root / "stats_grid.json"
            sp = root / "stats_sonnet.json"
            gp.write_text(json.dumps(stats), encoding="utf-8")
            sp.write_text(json.dumps(stats), encoding="utf-8")
            with mock.patch("premarket_ab_journal.STATS_GRID", gp), mock.patch(
                "premarket_ab_journal.STATS_SONNET", sp
            ), mock.patch("premarket_ab_pairing.STATS_GRID", gp), mock.patch(
                "premarket_ab_pairing.STATS_SONNET", sp
            ):
                wr = __import__("premarket_ab_returns").rolling_win_rate("grid")
            self.assertEqual(wr["wins"], 3)
            self.assertEqual(wr["losses"], 1)
            self.assertAlmostEqual(wr["win_rate"], 0.75)


class TestPremarketAbPairing(unittest.TestCase):
    def test_void_symmetry_excludes_both(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gp = root / "stats_grid.json"
            sp = root / "stats_sonnet.json"
            gp.write_text(
                json.dumps(
                    {
                        "2026-07-15": {"return_pct": 0.01},
                        "2026-07-16": {"return_pct": 0.02, "ab_void": True},
                    }
                ),
                encoding="utf-8",
            )
            sp.write_text(
                json.dumps(
                    {
                        "2026-07-15": {"return_pct": 0.015},
                        "2026-07-16": {"return_pct": 0.03},
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch("premarket_ab_journal.STATS_GRID", gp), mock.patch(
                "premarket_ab_journal.STATS_SONNET", sp
            ), mock.patch("premarket_ab_pairing.STATS_GRID", gp), mock.patch(
                "premarket_ab_pairing.STATS_SONNET", sp
            ):
                pairing = __import__("premarket_ab_pairing")
                dates = pairing.paired_scorable_dates()
            self.assertEqual(dates, ["2026-07-15"])

    def test_information_bucket_adjusted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            grid_j = root / "journal_grid.jsonl"
            sonnet_j = root / "journal_sonnet.jsonl"
            grid_j.write_text(
                json.dumps(
                    {
                        "date": "2026-07-15",
                        "chain": "grid",
                        "sym": "NVDA",
                        "dir": 1,
                        "info_basis": "snapshot",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            sonnet_j.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "date": "2026-07-15",
                                "chain": "sonnet",
                                "sym": "NVDA",
                                "dir": 1,
                                "info_basis": "snapshot",
                            }
                        ),
                        json.dumps(
                            {
                                "date": "2026-07-15",
                                "chain": "sonnet",
                                "sym": "PLTR",
                                "dir": 1,
                                "info_basis": "world-knowledge",
                                "attribution": "information",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            outcomes = {"NVDA": 0.02, "PLTR": 0.10}
            with mock.patch("premarket_ab_pairing.JOURNAL_GRID", grid_j), mock.patch(
                "premarket_ab_pairing.JOURNAL_SONNET", sonnet_j
            ):
                pairing = __import__("premarket_ab_pairing")
                raw_g, raw_s = pairing.daily_returns_for_date("2026-07-15", outcomes, adjusted=False)
                adj_g, adj_s = pairing.daily_returns_for_date("2026-07-15", outcomes, adjusted=True)
            self.assertAlmostEqual(raw_s, 0.06, places=4)
            self.assertAlmostEqual(adj_s, 0.02, places=4)
            self.assertAlmostEqual(raw_g, 0.02, places=4)
            self.assertAlmostEqual(adj_g, 0.02, places=4)

    def test_bootstrap_paired_diffs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gp = root / "stats_grid.json"
            sp = root / "stats_sonnet.json"
            gp.write_text(
                json.dumps(
                    {
                        "2026-07-15": {"return_pct": 0.01},
                        "2026-07-16": {"return_pct": 0.02},
                    }
                ),
                encoding="utf-8",
            )
            sp.write_text(
                json.dumps(
                    {
                        "2026-07-15": {"return_pct": 0.02, "adjusted_return_pct": 0.02},
                        "2026-07-16": {"return_pct": 0.03, "adjusted_return_pct": 0.025},
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch("premarket_ab_journal.STATS_GRID", gp), mock.patch(
                "premarket_ab_journal.STATS_SONNET", sp
            ), mock.patch("premarket_ab_pairing.STATS_GRID", gp), mock.patch(
                "premarket_ab_pairing.STATS_SONNET", sp
            ):
                pairing = __import__("premarket_ab_pairing")
                diffs = pairing.paired_daily_diffs(adjusted=False)
                adj_diffs = pairing.paired_daily_diffs(adjusted=True)
                boot = __import__("premarket_verdict_bootstrap").bootstrap_ab_ci()
            self.assertEqual(len(diffs), 2)
            self.assertAlmostEqual(diffs[0][1], 0.01, places=4)
            self.assertAlmostEqual(adj_diffs[1][1], 0.005, places=4)
            self.assertEqual(boot["resample_unit"], "paired_day_diff")
            self.assertEqual(boot["verdict_window_start"], "2026-07-15")


class TestPremarketAbSummary(unittest.TestCase):
    def test_build_summary_counts(self) -> None:
        with mock.patch(
            "premarket_ab_summary.fetch_premarket_from_store",
            side_effect=[
                [{"sym": "NVDA", "dir": 1, "value": "多 · [高置信]"}],
                [{"sym": "NVDA", "dir": 0, "value": "观察 · [观察]"}],
            ],
        ), mock.patch("premarket_ab_summary.rolling_return_pct", return_value=0.01), mock.patch(
            "premarket_ab_summary.rolling_win_rate", return_value={"wins": 2, "losses": 1, "n_scored": 3, "win_rate": 0.6667}
        ), mock.patch("premarket_ab_summary.fetch_day_returns", return_value={}), mock.patch(
            "premarket_ab_summary.reconcile_chain"
        ) as rc:
            rc.side_effect = [
                {"chain": "grid", "n_items": 1, "wins": 1, "losses": 0, "win_rate": 1.0, "return_pct": 0.02},
                {"chain": "sonnet", "n_items": 1, "wins": 0, "losses": 0, "win_rate": 0, "return_pct": None},
            ]
            s = __import__("premarket_ab_summary").build_premarket_ab_summary("2026-07-09")
        self.assertEqual(s["grid_n"], 1)
        self.assertEqual(s["sonnet_n"], 1)
        self.assertEqual(s["divergence_n"], 1)
        text = __import__("premarket_ab_summary").format_premarket_ab_brief_text(s)
        self.assertIn("盘前 A/B", text)
        self.assertIn("当日收益", text)
        self.assertIn("30d胜率", text)
        self.assertNotIn("⚡", text)


if __name__ == "__main__":
    unittest.main()
