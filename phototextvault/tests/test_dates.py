"""Tests for date resolution from filenames."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from phototextvault import dates


def test_parse_filename_screenshot_style(tmp_path: Path) -> None:
    p = tmp_path / "Screenshot 2025-08-03 at 10.14.22 AM.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")  # invalid png but name parses
    # resolve may fail PIL but filename wins before mtime in code - actually EXIF first fails, then filename
    d = dates.resolve_screenshot_date(p)
    assert d == date(2025, 8, 3)


def test_parse_img_style(tmp_path: Path) -> None:
    p = tmp_path / "IMG_20250815_001.png"
    p.write_bytes(b"x")
    d = dates._parse_filename_date(p.name)  # noqa: SLF001
    assert d == date(2025, 8, 15)
