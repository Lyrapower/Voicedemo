#!/usr/bin/env python3
"""Shim — 粒子页日记 canonical 入口在 aster-diary/diary.py。"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_TARGET = Path(__file__).resolve().parent.parent / "aster-diary" / "diary.py"
if not _TARGET.is_file():
    raise SystemExit(f"missing {_TARGET}")
sys.argv[0] = str(_TARGET)
runpy.run_path(str(_TARGET), run_name="__main__")
