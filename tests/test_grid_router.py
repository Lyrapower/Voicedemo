"""Tests — Grid Router v2.0: confirmation credentials, protected scope, cc_candidate E2E."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "scripts" / "grid" / "grid_router.py"


def _load_router():
    spec = importlib.util.spec_from_file_location("grid_router", ROUTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


gr = _load_router()
RULES = gr.DEFAULT_RULES


class ConfirmationCredentialTests(unittest.TestCase):
    def test_payload_cc_confirmed_bool(self):
        p = {"cc_confirmed": True, "cc_task": "analyze"}
        ok, kind = gr.parse_confirmation(p)
        self.assertTrue(ok)
        self.assertEqual(kind, "payload:cc_confirmed")

    def test_payload_confirmed_bool_automation(self):
        p = {"confirmed": True}
        ok, kind = gr.parse_confirmation(p)
        self.assertTrue(ok)
        self.assertEqual(kind, "payload:confirmed")

    def test_confirmed_string_rejected(self):
        p = {"confirmed": "true", "messages": [{"role": "user", "content": "/cloud x"}]}
        ok, kind = gr.parse_confirmation(p)
        self.assertFalse(ok)
        self.assertEqual(kind, "reject:non_bool_confirm")

    def test_message_confirm_chain_last_only(self):
        p = {
            "messages": [
                {"role": "user", "content": "/cloud review diff"},
                {"role": "user", "content": "CONFIRM"},
            ],
        }
        ok, kind = gr.parse_confirmation(p)
        self.assertTrue(ok)
        self.assertIn("CONFIRM", kind)

    def test_fake_confirm_in_history_not_last_rejected(self):
        p = {
            "messages": [
                {"role": "user", "content": "CONFIRM"},
                {"role": "user", "content": "/cloud do work"},
            ],
        }
        ok, kind = gr.parse_confirmation(p)
        self.assertFalse(ok)
        self.assertEqual(kind, "")

    def test_bare_confirm_without_anchor_rejected(self):
        p = {"messages": [{"role": "user", "content": "CONFIRM"}]}
        ok, kind = gr.parse_confirmation(p)
        self.assertFalse(ok)
        self.assertEqual(kind, "reject:bare_CONFIRM")

    def test_confirm_plus_cc_task_payload(self):
        p = {
            "cc_task": "long analysis task",
            "messages": [{"role": "user", "content": "CONFIRM"}],
        }
        ok, kind = gr.parse_confirmation(p)
        self.assertTrue(ok)
        self.assertEqual(kind, "message:CONFIRM+cc_task")


class ProtectedScopeTests(unittest.TestCase):
    def test_scope_field_authoritative(self):
        p = {"scope": "diary", "messages": [{"role": "user", "content": "anything"}]}
        blocked, reason = gr.protected_scope(RULES, p)
        self.assertTrue(blocked)
        self.assertTrue(reason.startswith("scope_field:"))

    def test_paraphrase_diary_stays_core(self):
        variants = [
            "open my daily log for tonight",
            "write a journal entry about pool",
            "看看今晚记的笔记",
        ]
        for text in variants:
            with self.subTest(text=text):
                p = {"messages": [{"role": "user", "content": "/cloud " + text}]}
                outcome, target, reason, _ = gr.decide(RULES, p, {})
                self.assertEqual(outcome, gr.OUTCOME_GRID_LOCAL, reason)
                self.assertEqual(target, gr.TARGET_CORE)

    def test_paraphrase_memory_palace_stays_core(self):
        variants = [
            "search memory palace vault room 3",
            "记忆宫殿里第三间有什么",
            "palace vault index",
        ]
        for text in variants:
            with self.subTest(text=text):
                p = {"messages": [{"role": "user", "content": text}]}
                blocked, reason = gr.protected_scope(RULES, p)
                self.assertTrue(blocked, reason)
                self.assertIn("domain:memory_palace", reason)

    def test_paraphrase_identity_stays_core(self):
        p = {"messages": [{"role": "user", "content": "tell me what are you really"}]}
        blocked, reason = gr.protected_scope(RULES, p)
        self.assertTrue(blocked)
        self.assertIn("domain:identity", reason)

    def test_assistant_history_does_not_trigger_protected(self):
        """assistant 历史含 diary 字样不能单独触发 — 仅末条 user + system。"""
        p = {
            "messages": [
                {"role": "assistant", "content": "diary entry from yesterday"},
                {"role": "user", "content": "analyze NVDA pool scan"},
            ],
        }
        blocked, _ = gr.protected_scope(RULES, p)
        self.assertFalse(blocked)


class CcCandidateResponseTests(unittest.TestCase):
    def test_candidate_body_shape(self):
        p = {"messages": [{"role": "user", "content": "/cloud review repo"}]}
        body = gr.cc_candidate_body(p, "slash:/cloud")
        self.assertEqual(body["choices"][0]["finish_reason"], "cc_candidate")
        meta = body["grid_meta"]
        self.assertTrue(meta["awaiting_confirmation"])
        self.assertEqual(meta["route_outcome"], gr.OUTCOME_CC_CANDIDATE)
        self.assertIn("confirm_credentials", meta)
        self.assertIn("cc_task_hint", meta)


class CcCandidateE2ETests(unittest.TestCase):
    def test_auto_candidate_then_cc_task_confirmed_executes_cli(self):
        task = "分析" + ("市场" * 260)
        p1 = {"messages": [{"role": "user", "content": task}]}
        o1, t1, _, _ = gr.decide(RULES, p1, {})
        self.assertEqual(o1, gr.OUTCOME_CC_CANDIDATE)
        self.assertIsNone(t1)

        p2 = {
            "cc_confirmed": True,
            "cc_task": task,
            "messages": [{"role": "user", "content": "CONFIRM"}],
        }
        o2, t2, reason, _ = gr.decide(RULES, p2, {})
        self.assertEqual(o2, gr.OUTCOME_CC_CLI)
        self.assertEqual(t2, gr.TARGET_CLOUD)
        self.assertTrue(reason.startswith("confirm:"))

        env = gr.task_scoped_envelope(p2)
        self.assertIn(task[:40], env)

        sent: list[tuple[int, dict]] = []

        def fake_send(code: int, body: dict, ctype: str = "") -> None:
            sent.append((code, body))

        handler = mock.Mock()
        handler._claim.return_value = True
        handler._send = fake_send
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler.wfile = mock.Mock()
        handler.wfile.write = mock.Mock()
        tgt = {"cmd": ["claude", "-p"], "extra_args": [], "timeout": 5, "model": "cc"}
        with mock.patch.object(gr.subprocess, "run") as run:
            run.return_value = mock.Mock(
                returncode=0,
                stdout=json.dumps({"result": "done"}).encode(),
                stderr=b"",
            )
            gr.forward_cli(handler, tgt, p2, "cloud")

        run.assert_called_once()
        prompt_in = run.call_args.kwargs.get("input") or b""
        self.assertIn(task[:40], prompt_in.decode("utf-8"))
        handler.send_response.assert_called_with(200)

    def test_slash_cloud_candidate_then_confirm_chain_executes_cli(self):
        p1 = {"messages": [{"role": "user", "content": "/cloud review repo"}]}
        o1, _, _, _ = gr.decide(RULES, p1, {})
        self.assertEqual(o1, gr.OUTCOME_CC_CANDIDATE)

        p2 = {
            "messages": [
                {"role": "user", "content": "/cloud review repo"},
                {"role": "user", "content": "CONFIRM"},
            ],
        }
        o2, t2, _, _ = gr.decide(RULES, p2, {})
        self.assertEqual(o2, gr.OUTCOME_CC_CLI)
        self.assertEqual(t2, gr.TARGET_CLOUD)
        self.assertEqual(gr.task_scoped_envelope(p2), "review repo")


class GridRouterDecideTests(unittest.TestCase):
    def test_default_is_grid_local(self):
        payload = {"messages": [{"role": "user", "content": "hello"}]}
        outcome, target, reason, _ = gr.decide(RULES, payload, {})
        self.assertEqual(outcome, gr.OUTCOME_GRID_LOCAL)
        self.assertEqual(target, gr.TARGET_CORE)

    def test_slash_scan_with_confirmed_automation(self):
        payload = {
            "confirmed": True,
            "messages": [{"role": "user", "content": "/scan pool tickers"}],
        }
        outcome, target, _, p2 = gr.decide(RULES, payload, {})
        self.assertEqual(outcome, gr.OUTCOME_CC_CLI)
        self.assertEqual(target, gr.TARGET_CLOUD)
        self.assertEqual(p2["messages"][0]["content"], "pool tickers")


class GridRouterCliFailureTests(unittest.TestCase):
    def test_nonzero_exit_returns_502(self):
        sent: list[tuple[int, dict]] = []

        def fake_send(code: int, body: dict, ctype: str = "") -> None:
            sent.append((code, body))

        handler = mock.Mock()
        handler._claim.return_value = True
        handler._send = fake_send
        tgt = {"cmd": ["claude", "-p"], "extra_args": [], "timeout": 5, "model": "cc"}
        payload = {"messages": [{"role": "user", "content": "task"}]}
        with mock.patch.object(gr.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stdout=b"", stderr=b"boom")
            gr.forward_cli(handler, tgt, payload, "cloud")
        self.assertEqual(sent[0][0], 502)


if __name__ == "__main__":
    unittest.main()
