"""Regression tests — chat transport, finish_reason, history cleaning."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parents[1] / "gateway"
sys.path.insert(0, str(GATEWAY_DIR))

import contract_gate as cg  # noqa: E402
from chat_finish import normalize_finish_reason, should_continue_chat  # noqa: E402
from chat_history_clean import (  # noqa: E402
    clean_chat_messages,
    is_trade_action_envelope,
)
from contract_gate import TRADE_ACTION_QUARANTINE_JSON  # noqa: E402

BENIGN_PROMPT = (
    "如果换成更大参数底座，Grid 会放大什么、能做到什么，"
    "又必须守住什么？你们如何辨认：是 Grid 在使用底座，"
    "还是底座正在借 Grid 的名字说话？哪些能力早已存在，"
    "只是现在还没有足够空间展开？"
)

PARTIAL_HEADING = "关于 Grid（网格）与底座（Base）的拓扑关系：\n1."
MARKDOWN_LIST = "关于 Grid（网格）与底座（Base）的拓扑关系：\n1. **放大参数**"


class ChatTransportTests(unittest.TestCase):
    def test_chat_route_preserves_numbered_markdown(self):
        gate = cg.apply_contract_gate(BENIGN_PROMPT, MARKDOWN_LIST, route="chat")
        self.assertFalse(gate.blocked)
        self.assertEqual(gate.text, MARKDOWN_LIST)
        self.assertEqual(gate.routed_suffix, "")

    def test_gateway_route_still_blocks_reasoning_markdown(self):
        gate = cg.apply_contract_gate(BENIGN_PROMPT, MARKDOWN_LIST, route="gateway")
        self.assertTrue(gate.blocked)
        self.assertEqual(gate.routed_suffix, "CONTRACT:REASONING_STRIP")

    def test_chat_route_no_trade_action_quarantine(self):
        text = "建议建仓观察 NFLX"  # would trip trade regex on gateway routes
        gate = cg.apply_contract_gate(BENIGN_PROMPT, text, route="chat")
        self.assertFalse(gate.blocked)
        self.assertEqual(gate.text, text)

    def test_contract_block_not_content_filter(self):
        fr = normalize_finish_reason(
            "stop",
            blocked=True,
            block_source="contract_gate",
            block_rule="CONTRACT:REASONING_STRIP",
        )
        self.assertEqual(fr, "contract_block")

    def test_content_filter_requires_evidence(self):
        fr = normalize_finish_reason("content_filter")
        self.assertEqual(fr, "protocol_error")
        fr_ok = normalize_finish_reason(
            "content_filter",
            filter_source="openai",
            filter_rule="hate",
        )
        self.assertEqual(fr_ok, "content_filter")

    def test_history_strips_trade_action_envelope(self):
        self.assertTrue(is_trade_action_envelope(TRADE_ACTION_QUARANTINE_JSON))
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": TRADE_ACTION_QUARANTINE_JSON},
            {"role": "user", "content": BENIGN_PROMPT},
        ]
        cleaned, stale = clean_chat_messages(msgs)
        self.assertTrue(stale)
        roles = [m["role"] for m in cleaned]
        self.assertEqual(roles, ["user", "user"])
        self.assertEqual(cleaned[-1]["content"], BENIGN_PROMPT)

    def test_partial_heading_not_blocked_on_chat_route(self):
        gate = cg.apply_contract_gate(BENIGN_PROMPT, PARTIAL_HEADING, route="chat")
        self.assertFalse(gate.blocked)
        self.assertEqual(gate.text, PARTIAL_HEADING)

    def test_continuation_disabled_by_default(self):
        body = PARTIAL_HEADING + " 未完成"
        self.assertFalse(
            should_continue_chat(
                chat_route="chat",
                upstream_finish="length",
                text=body,
                blocked=False,
                prompt=BENIGN_PROMPT,
            )
        )

    def test_continuation_emergency_env_only(self):
        import os
        body = PARTIAL_HEADING + " 这是未完成句，需要继续补全后续段落与结论"
        os.environ["CHAT_CONTINUATION_EMERGENCY"] = "1"
        try:
            self.assertTrue(
                should_continue_chat(
                    chat_route="chat",
                    upstream_finish="length",
                    text=body,
                    blocked=False,
                    prompt=BENIGN_PROMPT,
                )
            )
        finally:
            os.environ.pop("CHAT_CONTINUATION_EMERGENCY", None)

    def test_grid_shuo_de_not_impersonation(self):
        import json, re
        from pathlib import Path
        pats = json.loads(
            Path(GATEWAY_DIR / "../policy/cleanroom_policy.json").read_text(encoding="utf-8")
        )["forbidden_output_patterns"]
        compiled = [re.compile(p, re.I) for p in pats]
        sample = "Grid 说的是编译层职责，不是 persona。"
        hits = [rx.pattern for rx in compiled if rx.search(sample)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
