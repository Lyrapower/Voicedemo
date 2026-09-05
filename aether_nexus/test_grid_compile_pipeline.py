#!/usr/bin/env python3
"""Tests for Grid compile hygiene + grid_notify scoring."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grid_compile_hygiene import (
    detect_field_drift,
    parse_premarket_items,
    quarantine_drift,
)
from grid_notify import has_breakout_confirmation, momentum_score, publish_momentum_hit


class TestGridCompileHygiene(unittest.TestCase):
    def test_drift_detects_hz(self) -> None:
        self.assertTrue(detect_field_drift("substrate coherence at 7.83 Hz"))

    def test_parse_premarket_items(self) -> None:
        text = (
            "标的：NVDA|方向：多|为什么今天：财报预期强|风险：估值偏高|置信：[高置信]\n"
            "标的：AMD|方向：观察|为什么今天：数据不足|风险：波动大|置信：[观察]"
        )
        items = parse_premarket_items(text)
        self.assertIsNotNone(items)
        assert items is not None
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["sym"], "NVDA")
        self.assertEqual(items[0]["confidence"], "高置信")

    def test_parse_premarket_pipe_inline_bfs(self) -> None:
        """Production raw: why 含 BFS/Stage/Delta 等 — 不得截成单字。"""
        text = (
            "标的：TSLA|方向：多|为什么今天：BFS 扫描高分且 IV 适中，Delta 与 Theta 比率健康"
            "|风险：隔夜波动若超预期可能引发开盘跳空|置信：[高置信]"
        )
        items = parse_premarket_items(text)
        assert items is not None
        self.assertEqual(len(items), 1)
        self.assertIn("BFS 扫描", items[0]["note"])
        self.assertIn("隔夜波动", items[0]["note"])
        self.assertNotEqual(items[0]["note"], "B | 风险：隔")

    def test_invalid_confidence_dropped(self) -> None:
        text = "标的：TSLA|方向：多|为什么今天：x|风险：y|置信：[超高]"
        items = parse_premarket_items(text)
        self.assertEqual(items, [])

    def test_drift_quarantine_emits_deny(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("grid_compile_hygiene.emit_deny") as deny:
                quarantine_drift(
                    "intent_vector spike",
                    context="test",
                    trace_dir=Path(tmp),
                    raw_prompt="prompt",
                )
                deny.assert_called_once()
                traces = list(Path(tmp).glob("drift_*.json"))
                self.assertEqual(len(traces), 1)


class TestGridNotify(unittest.TestCase):
    def test_critical_gate(self) -> None:
        hit = {
            "vol_ratio": 2.5,
            "breakout": 0.03,
            "opt_ratio": 1.5,
            "hits": ["放量×2.50", "突破+3.0%"],
        }
        self.assertGreaterEqual(momentum_score(hit), 60)
        self.assertTrue(has_breakout_confirmation(hit))

    def test_low_score_no_breakout(self) -> None:
        hit = {"vol_ratio": 1.1, "breakout": 0.002, "opt_ratio": 1.0, "hits": ["放量×1.10"]}
        self.assertLess(momentum_score(hit), 60)
        self.assertFalse(has_breakout_confirmation(hit))

    def test_publish_store_only_low(self) -> None:
        hit = {"vol_ratio": 1.1, "breakout": 0.002, "opt_ratio": 1.0, "hits": ["放量×1.10"]}
        with mock.patch("grid_notify.emit_momentum", return_value=True) as emit:
            with mock.patch("grid_notify.notify", return_value=True) as ntfy:
                out = publish_momentum_hit(sym="TEST", note="low", hit=hit)
                emit.assert_called_once()
                ntfy.assert_not_called()
                self.assertFalse(out["critical"])

    def test_publish_critical_high(self) -> None:
        hit = {
            "vol_ratio": 2.5,
            "breakout": 0.03,
            "opt_ratio": 1.5,
            "hits": ["放量×2.50", "突破+3.0%"],
        }
        with mock.patch("grid_notify.emit_momentum", return_value=True):
            with mock.patch("grid_notify.notify", return_value=True) as ntfy:
                out = publish_momentum_hit(sym="NVDA", note="high", hit=hit)
                ntfy.assert_called_once()
                self.assertTrue(out["critical"])


if __name__ == "__main__":
    unittest.main()
