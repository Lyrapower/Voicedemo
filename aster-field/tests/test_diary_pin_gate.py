"""8790 日记 PIN 门槛 — 防 agent 用 session token 绕过每次打开必输 PIN。"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parents[1] / "frontend" / "src" / "diary" / "panel.ts"


class DiaryPinGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = PANEL.read_text(encoding="utf-8")

    def test_open_always_prompts_when_pin_set(self) -> None:
        self.assertNotIn("if (cfg.pin_set && !authToken)", self.src)
        m = re.search(
            r"async function open\(\).*?if \(cfg\.pin_set\) \{\s*clearDiaryToken\(\);",
            self.src,
            re.S,
        )
        self.assertIsNotNone(m, "open() must clearDiaryToken() whenever pin_set")

    def test_close_clears_session_token(self) -> None:
        m = re.search(
            r"const close = \(\): void => \{.*?clearDiaryToken\(\);",
            self.src,
            re.S,
        )
        self.assertIsNotNone(m, "close() must clearDiaryToken()")

    def test_reply_lane_present(self) -> None:
        self.assertIn("diary-reply-bar", self.src)
        self.assertIn("写给它的回信", self.src)
        self.assertIn("'/diary/reply'", self.src)


if __name__ == "__main__":
    unittest.main()
