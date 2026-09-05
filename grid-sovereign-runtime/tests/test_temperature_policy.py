"""Unit tests — per-task substrate temperature policy."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parents[1] / "gateway"
sys.path.insert(0, str(GATEWAY_DIR))

from temperature_policy import (  # noqa: E402
    CANDIDATE_INTEGRATE_TEMP,
    CHAT_DIALOGUE_TEMP,
    STRUCTURED_TASK_TEMP,
    is_candidate_integrate_request,
    resolve_substrate_temperature,
)


class TemperaturePolicyTests(unittest.TestCase):
    def test_chat_dialogue_default(self):
        temp = resolve_substrate_temperature(route_class="chat", body={}, messages=[])
        self.assertEqual(temp, CHAT_DIALOGUE_TEMP)

    def test_candidate_integrate_by_task_label(self):
        temp = resolve_substrate_temperature(
            route_class="chat",
            body={"task_label": "grid_candidate_integrate"},
            messages=[{"role": "user", "content": "hello"}],
        )
        self.assertEqual(temp, CANDIDATE_INTEGRATE_TEMP)

    def test_candidate_integrate_by_user_marker(self):
        temp = resolve_substrate_temperature(
            route_class="chat",
            body={},
            messages=[{
                "role": "user",
                "content": "问题:foo\n\n云端 candidate(仅参考,可修正或拒绝):\nbar\n\n请给出你的最终回答。",
            }],
        )
        self.assertEqual(temp, CANDIDATE_INTEGRATE_TEMP)

    def test_structured_routes_stay_low(self):
        for rc in ("compile", "task", "gateway"):
            temp = resolve_substrate_temperature(route_class=rc, body={})
            self.assertEqual(temp, STRUCTURED_TASK_TEMP)

    def test_tools_task_route_on_chat_completions(self):
        temp = resolve_substrate_temperature(
            route_class="task",
            body={"tools": [{"type": "function", "function": {"name": "x"}}]},
        )
        self.assertEqual(temp, STRUCTURED_TASK_TEMP)

    def test_kimi_candidate_label_not_integrate(self):
        self.assertFalse(
            is_candidate_integrate_request({"task_label": "grid_candidate"}, [])
        )


if __name__ == "__main__":
    unittest.main()
