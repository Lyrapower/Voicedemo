#!/usr/bin/env python3
"""Backward-compatible entry: runs scripts/photos_obsidian/pipeline.py (same env vars)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
_pipeline = _here / "scripts" / "photos_obsidian" / "pipeline.py"
sys.exit(subprocess.call([sys.executable, str(_pipeline)] + sys.argv[1:]))
