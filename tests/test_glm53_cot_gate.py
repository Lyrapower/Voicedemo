from __future__ import annotations

import unittest

from code_task.glm53_cot_gate import (
    GLM53_COT_RETRY_USER,
    content_looks_like_cot,
    is_glm53_lane,
    resolve_glm53_visible_content,
    retry_messages,
    strip_cot_to_answer,
    strip_think_tag,
)

PROBE_COT = (
    'The user is asking me to reply with just one character: "好" (which means '
    '"good" or "okay" in Chinese). This is a simple, harmless request for a '
    "minimal response. There's no complexity here — they explicitly want a "
    "single-character reply, so"
)


class Glm53CotGateTests(unittest.TestCase):
    def test_lane_detect(self) -> None:
        self.assertTrue(is_glm53_lane("glm53", None))
        self.assertTrue(is_glm53_lane("glm53_full", None))
        self.assertTrue(is_glm53_lane(None, "glm-5.3-flash:cloud"))
        self.assertTrue(is_glm53_lane(None, "glm-5.3:cloud"))
        self.assertFalse(is_glm53_lane("glm52", "glm-5.2:cloud"))

    def test_probe_dump_is_cot(self) -> None:
        self.assertTrue(content_looks_like_cot(PROBE_COT))

    def test_real_answers_are_not_cot(self) -> None:
        self.assertFalse(content_looks_like_cot("好"))
        self.assertFalse(content_looks_like_cot("市场今天偏弱，先看仓位。"))
        self.assertFalse(content_looks_like_cot("I think we should wait for confirmation."))
        self.assertFalse(content_looks_like_cot("The market closed lower on weak breadth."))

    def test_strip_after_marker(self) -> None:
        blob = PROBE_COT + "\n回答：\n好"
        self.assertEqual(strip_cot_to_answer(blob), "好")

    def test_strip_last_cjk_line(self) -> None:
        blob = PROBE_COT + "\n好"
        self.assertEqual(strip_cot_to_answer(blob), "好")

    def test_strip_trailing_cjk_after_english_cot(self) -> None:
        blob = (
            'The user is asking me to reply with only one character: "好". '
            "This is a simple instruction to follow.好"
        )
        self.assertEqual(strip_cot_to_answer(blob), "好")
        vis, action = resolve_glm53_visible_content(blob, retried=False)
        self.assertEqual((vis, action), ("好", "strip"))

    def test_strip_after_think_close(self) -> None:
        blob = (
            'The user is asking me to reply with only one character: "好". '
            "The instruction is clear: output only \"好\".</think>好"
        )
        self.assertEqual(strip_cot_to_answer(blob), "好")
        self.assertEqual(strip_cot_to_answer(PROBE_COT), "")

    def test_resolve_retry_then_clean(self) -> None:
        vis, action = resolve_glm53_visible_content(PROBE_COT, retried=False)
        self.assertEqual(action, "retry_needed")
        vis, action = resolve_glm53_visible_content(PROBE_COT, "好", retried=True)
        self.assertEqual((vis, action), ("好", "retry"))

    def test_resolve_retry_still_cot_blocks(self) -> None:
        vis, action = resolve_glm53_visible_content(PROBE_COT, PROBE_COT, retried=True)
        self.assertEqual((vis, action), ("", "block"))

    def test_resolve_strip_after_failed_retry(self) -> None:
        vis, action = resolve_glm53_visible_content(
            PROBE_COT, PROBE_COT + "\n\n先看仓位。", retried=True
        )
        self.assertEqual(action, "strip")
        self.assertEqual(vis, "先看仓位。")

    def test_english_cot_tail_is_not_stripped(self) -> None:
        blob = (
            PROBE_COT
            + '\n\nThe user\'s request is simple: reply with just "好". This is'
        )
        self.assertEqual(strip_cot_to_answer(blob), "")
        vis, action = resolve_glm53_visible_content(PROBE_COT, blob, retried=True)
        self.assertEqual((vis, action), ("", "block"))

    def test_retry_messages_isolates_last_user(self) -> None:
        msgs = retry_messages(
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "old"},
                {"role": "assistant", "content": "prev"},
                {"role": "user", "content": "hi"},
            ]
        )
        self.assertEqual([m["role"] for m in msgs], ["system", "user", "user"])
        self.assertEqual(msgs[1]["content"], "hi")
        self.assertEqual(msgs[-1]["content"], GLM53_COT_RETRY_USER)
        self.assertIn("The user is asking", GLM53_COT_RETRY_USER)

    # ----  imd 裸 CoT 漏出(strip_think_tag) ----

    def test_strip_think_tag_takes_after_close(self) -> None:
        leak = PROBE_COT + " Keep it short.</think>哈哈，这问题挺有意思"
        self.assertEqual(strip_think_tag(leak), "哈哈，这问题挺有意思")

    def test_strip_think_tag_last_close_wins(self) -> None:
        leak = "先想一段。</think>中间回复</think>最终回复"
        self.assertEqual(strip_think_tag(leak), "最终回复")

    def test_strip_think_tag_no_close_returns_original(self) -> None:
        self.assertEqual(strip_think_tag("纯回复，无标签"), "纯回复，无标签")
        self.assertEqual(strip_think_tag(""), "")

    def test_resolve_leak_pattern_returns_reply_ok(self) -> None:
        """真实事故模式:裸 CoT +  imd + 回复 → resolve 应直接给回复,action=ok."""
        leak = (
            "The user is asking casually how it feels to be here. I should respond "
            "in a friendly way. Keep response concise and warm.</think>哈哈，这问题问得挺有意思 😄"
        )
        vis, action = resolve_glm53_visible_content(leak, retried=False)
        self.assertEqual(action, "ok")
        self.assertEqual(vis, "哈哈，这问题问得挺有意思 😄")
        self.assertNotIn("The user is asking", vis)
        self.assertNotIn("Keep response concise", vis)


if __name__ == "__main__":
    unittest.main()
