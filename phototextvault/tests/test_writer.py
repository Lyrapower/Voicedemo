"""Tests for monthly window assignment."""

from __future__ import annotations

from datetime import date

from phototextvault.writer import window_for_date


def test_sep_first_belongs_to_sep_window() -> None:
    w = window_for_date(date(2025, 9, 1))
    assert w is not None
    assert w[2] == "2025-09_to_2025-10.md"


def test_aug_last_in_aug_window() -> None:
    w = window_for_date(date(2025, 8, 31))
    assert w is not None
    assert w[2] == "2025-08_to_2025-09.md"


def test_april_partial_last_day() -> None:
    w = window_for_date(date(2026, 4, 23))
    assert w is not None
    assert w[2] == "2026-04-01_to_2026-04-23.md"


def test_april_24_outside_windows() -> None:
    assert window_for_date(date(2026, 4, 24)) is None


def test_july_2025_outside() -> None:
    assert window_for_date(date(2025, 7, 31)) is None
