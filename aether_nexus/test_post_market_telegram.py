#!/usr/bin/env python3
"""Unit tests for post-market Telegram three-tier formatter."""
from __future__ import annotations

import datetime as dt
import unittest

from post_market_summary_daemon import (
    aggregate_log_flags,
    apply_stale_candidate_context,
    audit_rehearsal,
    build_stale_candidate_items,
    classify_telegram_tier,
    compute_trust_credit,
    effective_suspect_reasons,
    filter_dry_run_anomalies,
    format_telegram,
    has_scan_integrity_failure,
    is_rehearsal_meta,
    make_trace_id,
    reconcile_dry_run_final,
    resolve_effective_dry_run,
)
from aether_grid_emit import brief_items_from_final


class TestPostMarketTelegram(unittest.TestCase):
    def test_green_one_line(self) -> None:
        final = {
            "candidate_count": 5,
            "top_symbol": "NVDA",
            "top_score": 64.2,
            "anomaly_flags": [],
            "data_suspect": False,
        }
        msg = format_telegram(
            final,
            trade_date=dt.date(2026, 7, 3),
            dry_run=True,
            trace_id="0703a",
            trace_rel="traces/daemon/summary_2026-07-03_x.json",
            tier="green",
            suspect_reasons=[],
            log_flags={},
        )
        self.assertEqual(
            msg,
            "🟢 [DRY-RUN] Aether 07-03 · 5 candidates · top NVDA (64.2) · trace 0703a",
        )

    def test_yellow_with_fetch_fail(self) -> None:
        final = {
            "candidate_count": 5,
            "top_symbol": "NVDA",
            "top_score": 64.2,
            "anomaly_flags": [],
            "data_suspect": True,
        }
        msg = format_telegram(
            final,
            trade_date=dt.date(2026, 7, 3),
            dry_run=True,
            trace_id="0703a",
            trace_rel="traces/daemon/x.json",
            tier="yellow",
            suspect_reasons=["vote_disagreement"],
            log_flags={"fetch_fail": ["CSWI", "EXAMPLE"], "skip": [], "other": {}},
        )
        self.assertIn("有噪音,不用管", msg)
        self.assertIn("fetch_fail ×2 (CSWI, EXAMPLE)", msg)
        self.assertIn("parse_retry ×1", msg)
        self.assertIn("trace 0703a", msg)

    def test_red_quarantine(self) -> None:
        msg = format_telegram(
            {"candidate_count": 0, "top_symbol": "", "top_score": 0.0, "data_suspect": True, "anomaly_flags": []},
            trade_date=dt.date(2026, 7, 3),
            dry_run=True,
            trace_id="0703a",
            trace_rel="traces/daemon/summary_2026-07-03_0703a.json",
            tier="red",
            suspect_reasons=["gateway_parse_fail×3"],
            log_flags={},
            quarantined=True,
        )
        self.assertIn("需要你看一眼", msg)
        self.assertIn("summary unavailable", msg)
        self.assertIn("quarantine", msg)
        self.assertIn("→ 需要人工: traces/daemon/", msg)

    def test_theta_unit_whitelist(self) -> None:
        lines = [
            "2026-07-03 15:30:00,000 - INFO - NVDA: score=64.2",
            "2026-07-03 15:30:01,000 - WARNING - theta-unit check NVDA: alpaca=-0.1 bs_daily=-0.09 ratio=1.1 (~1 expected)",
        ]
        flags = aggregate_log_flags(lines)
        self.assertEqual(flags["fetch_fail"], [])
        self.assertEqual(flags["other"], {})

    def test_fetch_fail_parsed(self) -> None:
        lines = [
            "2026-07-03 15:30:00,000 - WARNING - Catalyst Stage 2 fetch failed: CSWI [perilla]",
            "2026-07-03 15:30:01,000 - WARNING - Catalyst Stage 2 fetch failed: MKSI [perilla]",
        ]
        flags = aggregate_log_flags(lines)
        self.assertEqual(flags["fetch_fail"], ["CSWI", "MKSI"])

    def test_trace_id(self) -> None:
        self.assertEqual(make_trace_id(dt.date(2026, 7, 3), "20260704_153045"), "2026-07-03_20260704_153045")

    def test_tier_classification(self) -> None:
        final = {"candidate_count": 5, "top_symbol": "NVDA", "top_score": 64.0, "data_suspect": False, "anomaly_flags": []}
        self.assertEqual(
            classify_telegram_tier(
                final=final,
                suspect_reasons=[],
                log_flags={},
                quarantined=False,
                summary_available=True,
            ),
            "green",
        )
        self.assertEqual(
            classify_telegram_tier(
                final=final,
                suspect_reasons=["gateway_parse_fail×3"],
                log_flags={},
                quarantined=False,
                summary_available=True,
            ),
            "yellow",
        )
        self.assertEqual(
            classify_telegram_tier(
                final=final,
                suspect_reasons=["gateway_parse_fail×3"],
                log_flags={},
                quarantined=False,
                summary_available=False,
            ),
            "red",
        )

    def test_resolve_effective_dry_run_default(self) -> None:
        self.assertTrue(resolve_effective_dry_run(cli_dry_run=False))

    def test_filter_dry_run_anomalies(self) -> None:
        flags = [
            "WARN: Dry run mode detected - no live data processed",
            "WARN: Pool scan window (09:35) has passed relative to log timestamp (10:05)",
            "WARN: real issue",
        ]
        out = filter_dry_run_anomalies(flags, dry_run=True)
        self.assertEqual(out, ["WARN: real issue"])

    def test_is_rehearsal_meta(self) -> None:
        meta = {"grid_meta": {"draft_only": True, "computed_verdict": "DRAFT_ECHO", "production": False}}
        self.assertTrue(is_rehearsal_meta(meta))
        self.assertTrue(audit_rehearsal([meta]))
        task_meta = {
            "grid_meta": {
                "draft_only": True,
                "computed_verdict": "DRAFT_ECHO",
                "production": False,
                "budget_route": "task",
            }
        }
        self.assertFalse(is_rehearsal_meta(task_meta))
        self.assertFalse(audit_rehearsal([task_meta]))

    def test_ground_from_premarket_journal(self) -> None:
        from post_market_summary_daemon import ground_from_premarket

        g = ground_from_premarket("2026-07-16")
        self.assertEqual(g.get("top_symbol"), "NVDA")
        self.assertGreaterEqual(g.get("candidate_count", 0), 5)

    def test_compute_trust_credit(self) -> None:
        final = {"data_suspect": False}
        self.assertFalse(
            compute_trust_credit(
                dry_run=True,
                rehearsal=False,
                tier="green",
                final=final,
                suspect_reasons=[],
            )
        )
        self.assertFalse(
            compute_trust_credit(
                dry_run=False,
                rehearsal=True,
                tier="green",
                final=final,
                suspect_reasons=[],
            )
        )
        self.assertTrue(
            compute_trust_credit(
                dry_run=False,
                rehearsal=False,
                tier="green",
                final=final,
                suspect_reasons=[],
            )
        )

    def test_dry_run_reconcile_ground_truth(self) -> None:
        ground = {"candidate_count": 5, "top_symbol": "NVDA", "top_score": 64.9}
        final = {"candidate_count": 0, "top_symbol": "", "top_score": 0.0, "data_suspect": True, "anomaly_flags": ["X"]}
        out = reconcile_dry_run_final(final, ground, rehearsal=True)
        self.assertEqual(out["top_symbol"], "NVDA")
        self.assertFalse(out["data_suspect"])

    def test_dry_run_days_log_dedup(self) -> None:
        state = {"dry_run_days_log": ["2026-07-03"], "completed_dates": []}
        from post_market_summary_daemon import record_dry_run_day, _normalize_state

        record_dry_run_day(state, dt.date(2026, 7, 7))
        record_dry_run_day(state, dt.date(2026, 7, 7))
        out = _normalize_state(state)
        self.assertEqual(out["dry_run_days_log"], ["2026-07-03", "2026-07-07"])
        self.assertEqual(out["dry_run_days_completed"], 2)

    def test_dry_run_tier_yellow_not_red(self) -> None:
        final = {"candidate_count": 5, "top_symbol": "NVDA", "top_score": 64.0, "data_suspect": False, "anomaly_flags": []}
        reasons = effective_suspect_reasons(["rehearsal_route", "log_error ×2"], dry_run=True)
        self.assertEqual(reasons, ["log_error ×2"])
        tier = classify_telegram_tier(
            final=final,
            suspect_reasons=reasons,
            log_flags={"other": {"log_error": 2}},
            quarantined=False,
            summary_available=True,
            dry_run=True,
        )
        self.assertEqual(tier, "yellow")

    def test_scan_integrity_forces_degraded_tier(self) -> None:
        final = {
            "candidate_count": 5,
            "top_symbol": "NVDA",
            "top_score": 64.0,
            "anomaly_flags": ["SCAN_ABORTED", "UNIVERSE_EMPTY"],
            "data_suspect": False,
            "scan_valid": False,
        }
        tier = classify_telegram_tier(
            final=final,
            suspect_reasons=[],
            log_flags={},
            quarantined=False,
            summary_available=True,
            dry_run=True,
            scan_integrity_failed=True,
        )
        self.assertEqual(tier, "yellow")

    def test_scan_integrity_degraded_message(self) -> None:
        final = apply_stale_candidate_context(
            {
                "candidate_count": 0,
                "top_symbol": "",
                "top_score": 0.0,
                "anomaly_flags": ["SCAN_ABORTED", "UNIVERSE_EMPTY"],
                "data_suspect": True,
            },
            {
                "candidate_count": 5,
                "top_symbol": "NVDA",
                "top_score": 64.93,
                "parsed_score_rows": [("NVDA", 64.93), ("PLTR", 58.59)],
                "last_scan_aborted": True,
            },
            scan_integrity_failed=True,
        )
        msg = format_telegram(
            final,
            trade_date=dt.date(2026, 7, 7),
            dry_run=True,
            trace_id="0707a",
            trace_rel="traces/daemon/x.json",
            tier="yellow",
            suspect_reasons=[],
            log_flags={},
            scan_integrity_failed=True,
        )
        self.assertIn("本次无有效扫描,数据链路故障", msg)
        self.assertNotIn("不用管", msg)
        self.assertIn("候选来自", msg)
        self.assertIn("非本次扫描产出", msg)

    def test_brief_items_src_on_scan_abort(self) -> None:
        final = apply_stale_candidate_context(
            {
                "candidate_count": 0,
                "top_symbol": "",
                "top_score": 0.0,
                "anomaly_flags": ["SCAN_ABORTED"],
                "data_suspect": True,
            },
            {
                "parsed_score_rows": [("NVDA", 64.93), ("PLTR", 58.59)],
                "top_symbol": "NVDA",
                "top_score": 64.93,
            },
            scan_integrity_failed=True,
        )
        items = brief_items_from_final(final)
        self.assertTrue(any(i.get("src") == final.get("candidate_source") for i in items if i.get("sym") not in ("—",)))
        self.assertTrue(
            any("候选来自缓存,非本次扫描产出" in str(i.get("value", "")) for i in items)
        )

    def test_integrity_failure_skips_reconcile_fill(self) -> None:
        ground = {
            "candidate_count": 5,
            "top_symbol": "NVDA",
            "top_score": 64.9,
            "parsed_score_rows": [("NVDA", 64.9)],
            "last_scan_aborted": True,
        }
        final = reconcile_dry_run_final(
            {"candidate_count": 0, "top_symbol": "", "top_score": 0.0, "anomaly_flags": ["SCAN_ABORTED"], "data_suspect": True},
            ground,
            rehearsal=True,
            scan_integrity_failed=True,
        )
        self.assertFalse(final.get("scan_valid", True))
        self.assertTrue(final.get("data_suspect"))
        self.assertTrue(final.get("stale_candidates"))

    def test_integrity_failure_no_trust_credit(self) -> None:
        final = {"data_suspect": False, "scan_valid": False}
        self.assertFalse(
            compute_trust_credit(
                dry_run=False,
                rehearsal=False,
                tier="yellow",
                final=final,
                suspect_reasons=[],
                scan_integrity_failed=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
