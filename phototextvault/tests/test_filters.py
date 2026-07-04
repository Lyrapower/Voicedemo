"""Tests for screenshot filename filtering."""

from __future__ import annotations

from pathlib import Path

from phototextvault import filters


def test_png_screenshot_name_ok(tmp_path: Path) -> None:
    p = tmp_path / "Screenshot 2025-08-01.png"
    p.write_text("x")
    ok, _ = filters.should_process(p, include_jpg=False, include_all_png=False)
    assert ok


def test_png_random_name_skipped(tmp_path: Path) -> None:
    p = tmp_path / "vacation.png"
    p.write_text("x")
    ok, reason = filters.should_process(p, include_jpg=False, include_all_png=False)
    assert not ok
    assert "screenshotish" in reason or "png_not" in reason


def test_jpg_skipped_by_default(tmp_path: Path) -> None:
    p = tmp_path / "Screenshot 2025-08-01.jpg"
    p.write_text("x")
    ok, _ = filters.should_process(p, include_jpg=False, include_all_png=False)
    assert not ok


def test_jpg_with_flag(tmp_path: Path) -> None:
    p = tmp_path / "Screenshot 2025-08-01.jpg"
    p.write_text("x")
    ok, _ = filters.should_process(p, include_jpg=True, include_all_png=False)
    assert ok


def test_include_all_png(tmp_path: Path) -> None:
    p = tmp_path / "foo.png"
    p.write_text("x")
    ok, _ = filters.should_process(p, include_jpg=False, include_all_png=True)
    assert ok
