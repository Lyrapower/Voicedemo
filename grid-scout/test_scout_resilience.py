#!/usr/bin/env python3
"""Unit tests for scout resilience helpers (no live LLM)."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path("/Users/ciciwang/Projects/demo")
SCOUT = ROOT / "grid-scout"
sys.path.insert(0, str(SCOUT))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRepairJson(unittest.TestCase):
    def test_truncated_candidates_salvage(self):
        import scout_agent
        if not hasattr(scout_agent, "_repair_json_obj"):
            self.skipTest("3.31.1 无 _repair_json_obj")
        text = '{"macro":{"sp500_bias":"中性"},"candidates":[{"ticker":"AAA","direction":"call"},{"ticker":"BBB"'
        data = scout_agent._repair_json_obj(text)
        self.assertIsInstance(data, dict)
        self.assertIn("candidates", data)
        self.assertGreaterEqual(len(data["candidates"]), 1)

    def test_extract_prefers_closed(self):
        import scout_agent
        text = 'noise {"a":1,"candidates":[{"ticker":"X"}]} trailing'
        data = scout_agent._extract_json(text)
        self.assertEqual(data["a"], 1)


class TestWaitHttp(unittest.TestCase):
    def test_wait_ok_first_try(self):
        import scout_agent
        if not hasattr(scout_agent, "wait_http_ok"):
            self.skipTest("3.31.1 无 wait_http_ok")

        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"{}"

        with mock.patch("urllib.request.urlopen", return_value=Resp()):
            self.assertTrue(scout_agent.wait_http_ok("http://127.0.0.1:9/x", attempts=2, sleep_s=0))

    def test_wait_fails(self):
        import scout_agent
        if not hasattr(scout_agent, "wait_http_ok"):
            self.skipTest("3.31.1 无 wait_http_ok")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            with mock.patch.object(scout_agent, "_maybe_kick_dep"):
                self.assertFalse(
                    scout_agent.wait_http_ok("http://127.0.0.1:9/x", attempts=2, sleep_s=0)
                )


class TestOfficerCallRetry(unittest.TestCase):
    def test_empty_then_ok(self):
        import scout_agent
        empty = {"content": ""}
        ok = {"content": '{"candidates":[]}'}
        with mock.patch.object(scout_agent, "_http", side_effect=[empty, ok]):
            out = scout_agent.glm_officer_call("hi")
        self.assertIn("candidates", out)

    def test_persist_false_glm52(self):
        import scout_agent
        captured = {}
        def fake_http(url, body=None, headers=None, timeout=120):
            captured["url"] = url
            captured["body"] = body
            return {"content": "ok"}
        with mock.patch.object(scout_agent, "_http", side_effect=fake_http):
            out = scout_agent.glm_officer_call("hi")
        self.assertEqual(out, "ok")
        self.assertTrue(str(captured["url"]).endswith("/task/cloud_chat"))
        self.assertEqual(captured["body"].get("substrate"), "glm52")
        self.assertIs(captured["body"].get("persist"), False)


class TestFmpBoardSelfRet(unittest.TestCase):
    def test_shell_on_official_not_main(self):
        import scout_agent
        cross = {
            "market_movers": [{"side": "gainers", "symbol": "SHEL", "price": 3, "chg_pct": 40}],
            "most_active": [],
            "trend_board": [],
            "self_ret1d_board": [],
        }
        board = scout_agent.fmp_board_syms(cross)
        self.assertNotIn("SHEL", board)
        self.assertIn("SHEL", cross.get("ref_rank") or [])


class TestLandEmitRetry(unittest.TestCase):
    def test_emit_retries_then_ok(self):
        land = _load("scout_land_option", ROOT / "scripts" / "scout_land_option.py")

        class Bad:
            def __enter__(self): raise OSError("down")
            def __exit__(self, *a): return False

        class Good:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        seq = [Bad(), Good()]

        def fake_open(*a, **k):
            return seq.pop(0)

        with mock.patch.object(land, "wait_gw", return_value=True):
            with mock.patch("urllib.request.urlopen", side_effect=fake_open):
                with mock.patch.object(land, "time") as t:
                    t.sleep = lambda *_: None
                    land.emit("2026-08-12", "t", "b", Path("/tmp/x"), {"candidates": []}, {}, "", {})


class TestLandGlmHardGate(unittest.TestCase):
    def test_empty_glm_source_refuses_placeholder(self):
        src = (ROOT / "scripts" / "scout_land_option.py").read_text(encoding="utf-8")
        self.assertIn("禁止把 DS 直出当", src)
        self.assertIn('origin != "glm52_cloud"', src)
        self.assertIn("write_public_html_from_glm", src)
        self.assertIn("--mode", src)
        self.assertIn("midday", src)
        self.assertNotIn("(glm empty — ds json landed)", src)

    def test_scout_agent_shifts_call_land(self):
        src = (SCOUT / "scout_agent.py").read_text(encoding="utf-8")
        self.assertIn("def glm_land_or_die", src)
        self.assertIn("def glm_morning_land_or_die", src)
        self.assertIn("glm_land_or_die(today, shift)", src)
        self.assertIn("GLM_LAND_SHIFTS", src)
        self.assertIn("write_public_html_from_glm", src)
        self.assertIn("晚报禁止落盘", src)
        self.assertIn("evening-final.md", src)


class TestGlmPublicHtml(unittest.TestCase):
    def test_glm_html_renders_four_slot_cards(self):
        import scout_agent
        md = open(SCOUT / "briefs" / "2026-08-27-morning-final.md", encoding="utf-8").read()
        html = scout_agent.render_glm_brief_html("2026-08-27", "morning", md, {"down_count": 1, "of": 6})
        self.assertIn("review_origin=glm52_cloud", html)
        self.assertIn("GLM 编译终稿", html)
        self.assertIn("二 · 四槽股票卡", html)
        for t in ("PATH", "NVDA", "RBRK", "ADSK"):
            self.assertIn(t, html)
        self.assertIn("pill kill", html)
        self.assertIn("作废", html)
        self.assertNotIn("一 · 大盘方向", html)
        self.assertIn('class="engine-fold"', html)
        slots = scout_agent.parse_glm_slots(md)
        self.assertEqual([s["ticker"] for s in slots], ["PATH", "NVDA", "RBRK", "ADSK"])

    def test_glm_html_without_table_falls_back_md(self):
        import scout_agent
        md = "# Scout 晨会\n\n> review_origin=glm52_cloud · review_ts=x\n\nPATH 已作废,不写做多。"
        html = scout_agent.render_glm_brief_html("2026-08-27", "morning", md, {"down_count": 1, "of": 6})
        self.assertIn("PATH 已作废", html)
        self.assertIn("GLM 编译终稿", html)

    def test_stub_is_not_a_landed_page(self):
        import scout_agent
        stub = scout_agent._pending_glm_stub_html("2026-08-27", "midday")
        self.assertIn("待 GLM 编译", stub)
        self.assertNotIn("review_origin=glm52_cloud", stub)
        self.assertNotIn("GLM 编译终稿", stub)

    def test_render_console_glm_shift_writes_stub_not_ds_public(self):
        import scout_agent
        import tempfile, os
        old = scout_agent.OUT
        try:
            with tempfile.TemporaryDirectory() as td:
                scout_agent.OUT = td
                with mock.patch.object(scout_agent, "_http", side_effect=RuntimeError("test-no-console")):
                    scout_agent.render_console(
                        "t", "body", "2026-08-27", "midday",
                        {"candidates": [{"ticker": "NVDA", "slot": 4, "empty": False}],
                         "macro": {"sp500_bias": "看涨", "logic": "x", "key_levels": "y"},
                         "hedge": {"distribution_risk": "低"}},
                        {"down_count": 0, "of": 6},
                    )
                with open(os.path.join(td, "briefs", "2026-08-27-midday.html"), encoding="utf-8") as f:
                    pub = f.read()
                with open(os.path.join(td, "briefs", "2026-08-27-midday.ds.html"), encoding="utf-8") as f:
                    ds = f.read()
                self.assertIn("待 GLM 编译", pub)
                self.assertNotIn("review_origin=glm52_cloud", pub)
                self.assertIn("NVDA", ds)
        finally:
            scout_agent.OUT = old


class TestEngineKvFold(unittest.TestCase):
    def test_engine_card_is_collapsed_details(self):
        import scout_agent
        html = scout_agent._engine_card({
            "down_count": 3, "of": 6, "vix_chg_pct": -1.71,
            "liquidation_watch": False, "tape_flags": {},
        })
        self.assertIn('class="engine-fold"', html)
        self.assertIn("<details", html)
        self.assertNotIn("<details open", html)
        self.assertIn("点击展开", html)
        self.assertIn("风险资产收跌", html)

    def test_job_sheet_precedes_engine_wall(self):
        import scout_agent
        html = scout_agent.render_brief_html(
            "2026-08-27", "morning",
            {"macro": {"sp500_bias": "看涨", "logic": "x", "key_levels": "y"},
             "candidates": [], "hedge": {"distribution_risk": "低"},
             "no_candidate_reason": "test"},
            "",
            {"down_count": 1, "of": 6, "vix_chg_pct": -1.0, "liquidation_watch": False},
        )
        self.assertLess(html.find("晨会交易任务单"), html.find('<details class="engine-fold"'))
        self.assertLess(html.find("一 · 大盘方向"), html.find('<details class="engine-fold"'))


if __name__ == "__main__":
    unittest.main()
