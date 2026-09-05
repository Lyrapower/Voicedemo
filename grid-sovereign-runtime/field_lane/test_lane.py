#!/usr/bin/env python3
from __future__ import annotations

import unittest

from field_lane.lane import classify_task, node_for_task, NODE_CHAT, NODE_COMPILE


class TestFieldLane(unittest.TestCase):
    def test_compile_routes_to_compile_node(self):
        self.assertEqual(node_for_task("compile_json"), NODE_COMPILE)
        self.assertEqual(node_for_task("chat"), NODE_CHAT)

    def test_classify_compile_json(self):
        self.assertEqual(classify_task("please compile_json schema for handoff"), "compile_json")


if __name__ == "__main__":
    unittest.main()
