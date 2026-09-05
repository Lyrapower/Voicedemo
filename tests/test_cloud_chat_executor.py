from __future__ import annotations

import unittest

from code_task.cloud_chat_executor import (
    TRIM_PAIRS_ON_EMPTY,
    _attach_images_last_user,
    cloud_attempt_plan,
)


class CloudChatExecutorPolicyTests(unittest.TestCase):
    def test_short_chat_allows_think_then_fallback(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        plan = cloud_attempt_plan(msgs)
        self.assertEqual(plan, [(True, "think"), (False, "no_think_fallback")])

    def test_memory_heavy_skips_think(self) -> None:
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(3):
            msgs.append({"role": "user", "content": f"u{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})
        plan = cloud_attempt_plan(msgs)
        self.assertEqual(plan, [(False, "no_think_memory")])

    def test_trim_escalation_defined(self) -> None:
        self.assertEqual(TRIM_PAIRS_ON_EMPTY[0], 0)
        self.assertGreater(max(TRIM_PAIRS_ON_EMPTY), 0)

    def test_deepseek_always_no_think(self) -> None:
        msgs = [{"role": "user", "content": "hi"}]
        self.assertEqual(
            cloud_attempt_plan(msgs, substrate="deepseek_v4"),
            [(False, "no_think_deepseek")],
        )
        self.assertEqual(
            cloud_attempt_plan(msgs, model="deepseek-v4-pro:cloud"),
            [(False, "no_think_deepseek")],
        )

    def test_glm53_always_think_channel(self) -> None:
        msgs = [{"role": "user", "content": "hi"}]
        self.assertEqual(
            cloud_attempt_plan(msgs, substrate="glm53"),
            [(True, "think_glm53")],
        )
        self.assertEqual(
            cloud_attempt_plan(msgs, model="glm-5.3-flash:cloud"),
            [(True, "think_glm53")],
        )
        self.assertEqual(
            cloud_attempt_plan(msgs, substrate="glm53_full"),
            [(True, "think_glm53")],
        )
        self.assertEqual(
            cloud_attempt_plan(msgs, model="glm-5.3:cloud"),
            [(True, "think_glm53")],
        )
        # short glm52 still allows think
        self.assertEqual(
            cloud_attempt_plan(msgs, substrate="glm52"),
            [(True, "think"), (False, "no_think_fallback")],
        )


class CloudChatPayloadThinkTests(unittest.TestCase):
    def test_think_false_is_explicit(self) -> None:
        from code_task.backends.glm52_cloud import chat_payload

        p = chat_payload(
            [{"role": "user", "content": "x"}],
            model="glm-5.2:cloud",
            max_tokens=64,
            temperature=0.3,
            think=False,
        )
        self.assertIn("think", p)
        self.assertIs(p["think"], False)

    def test_attach_images_last_user(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "see"},
        ]
        out = _attach_images_last_user(
            msgs, [{"mime": "image/png", "base64": "abc"}]
        )
        self.assertEqual(out[-1]["images"], ["abc"])
        self.assertEqual(out[-1]["content"], "see")


class _FakeOllamaResp:
    def __init__(self, content: str, done: str = "stop") -> None:
        self._content = content
        self._done = done

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "message": {"content": self._content},
            "done_reason": self._done,
            "model": "glm-5.3-flash:cloud",
            "eval_count": 8,
        }


class _FakeOllamaClient:
    def __init__(self, queue: list[_FakeOllamaResp]) -> None:
        self.queue = list(queue)
        self.posts = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None):
        self.posts += 1
        if not self.queue:
            raise AssertionError("unexpected extra Ollama POST")
        return self.queue.pop(0)


class CloudChatGlm53CotExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_think_channel_clean_content_passes(self) -> None:
        from unittest.mock import patch

        from code_task.cloud_chat_executor import execute_cloud_chat

        client = _FakeOllamaClient([_FakeOllamaResp("哈哈，挺好的。")])
        with patch("code_task.cloud_chat_executor.httpx.AsyncClient", return_value=client):
            resp = await execute_cloud_chat(
                request_id="t0",
                messages=[{"role": "user", "content": "感觉怎么样"}],
                endpoint="http://127.0.0.1:11434/api/chat",
                model="glm-5.3-flash:cloud",
                build_messages=lambda ms: list(ms),
                source="cloud_chat:glm53",
                substrate="glm53",
                max_tokens=512,
            )
        self.assertTrue(resp.ok)
        self.assertEqual(resp.content, "哈哈，挺好的。")
        self.assertEqual(resp.usage.get("cloud_policy"), "think_glm53")
        self.assertEqual(client.posts, 1)

    async def test_retry_keeps_clean_second(self) -> None:
        from unittest.mock import patch

        from code_task.cloud_chat_executor import execute_cloud_chat
        from tests.test_glm53_cot_gate import PROBE_COT

        client = _FakeOllamaClient(
            [_FakeOllamaResp(PROBE_COT, "length"), _FakeOllamaResp("好")]
        )
        with patch("code_task.cloud_chat_executor.httpx.AsyncClient", return_value=client):
            resp = await execute_cloud_chat(
                request_id="t1",
                messages=[{"role": "user", "content": "只回一个字:好"}],
                endpoint="http://127.0.0.1:11434/api/chat",
                model="glm-5.3-flash:cloud",
                build_messages=lambda ms: list(ms),
                source="cloud_chat:glm53",
                substrate="glm53",
                max_tokens=64,
            )
        self.assertTrue(resp.ok)
        self.assertEqual(resp.content, "好")
        self.assertEqual(resp.usage.get("cloud_policy"), "think_glm53_cot_retry")
        self.assertEqual(client.posts, 2)

    async def test_double_cot_is_blocked(self) -> None:
        from unittest.mock import patch

        from code_task.cloud_chat_executor import execute_cloud_chat
        from tests.test_glm53_cot_gate import PROBE_COT

        client = _FakeOllamaClient(
            [_FakeOllamaResp(PROBE_COT, "length"), _FakeOllamaResp(PROBE_COT, "length")]
        )
        with patch("code_task.cloud_chat_executor.httpx.AsyncClient", return_value=client):
            resp = await execute_cloud_chat(
                request_id="t2",
                messages=[{"role": "user", "content": "只回一个字:好"}],
                endpoint="http://127.0.0.1:11434/api/chat",
                model="glm-5.3-flash:cloud",
                build_messages=lambda ms: list(ms),
                source="cloud_chat:glm53",
                substrate="glm53",
                max_tokens=64,
            )
        self.assertFalse(resp.ok)
        self.assertEqual(resp.content, "")
        self.assertEqual(resp.done_reason, "cot_in_content")
        self.assertEqual((resp.error or {}).get("type"), "cot_in_content")
        self.assertEqual(client.posts, 2)

    async def test_trailing_cjk_strips_without_retry(self) -> None:
        from unittest.mock import patch

        from code_task.cloud_chat_executor import execute_cloud_chat

        blob = (
            'The user is asking me to reply with only one character: "好". '
            "This is a simple instruction to follow.好"
        )
        client = _FakeOllamaClient([_FakeOllamaResp(blob, "stop")])
        with patch("code_task.cloud_chat_executor.httpx.AsyncClient", return_value=client):
            resp = await execute_cloud_chat(
                request_id="t3",
                messages=[{"role": "user", "content": "只回一个字:好"}],
                endpoint="http://127.0.0.1:11434/api/chat",
                model="glm-5.3-flash:cloud",
                build_messages=lambda ms: list(ms),
                source="cloud_chat:glm53",
                substrate="glm53",
                max_tokens=64,
            )
        self.assertTrue(resp.ok)
        self.assertEqual(resp.content, "好")
        self.assertEqual(resp.usage.get("cloud_policy"), "think_glm53_cot_strip")
        self.assertEqual(client.posts, 1)


if __name__ == "__main__":
    unittest.main()
