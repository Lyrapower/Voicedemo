"""Shim — Cloud attachments live in code_task (8501). See tests/test_cloud_attachments.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_cloud_attachments import CloudAttachmentTests  # noqa: E402,F401

if __name__ == "__main__":
    unittest.main()
