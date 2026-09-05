import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import field_distill


class FieldDistillReexportTests(unittest.TestCase):
    @patch("field_lane.distill._http_json")
    def test_emit_via_shared_module(self, mock_http):
        field_distill.emit_event("queued", task="chat", node_id="field-particle")
        body = mock_http.call_args[0][1]
        self.assertEqual(body["source"], "field_distill")


if __name__ == "__main__":
    unittest.main()
