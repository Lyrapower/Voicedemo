"""Token budget — client ceiling respected."""
from __future__ import annotations

import unittest

from token_budget import resolve_max_tokens


class TokenBudgetTests(unittest.TestCase):
    def test_client_max_is_ceiling_not_ignored(self) -> None:
        cfg = {"chat_max_tokens": 8192}
        self.assertEqual(resolve_max_tokens("chat", 2048, cfg), 2048)
        self.assertEqual(resolve_max_tokens("chat", None, cfg), 8192)
        self.assertEqual(resolve_max_tokens("chat", 99999, cfg), 8192)


if __name__ == "__main__":
    unittest.main()
