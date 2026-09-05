"""Tests for off-pool A/B fabrication metrics."""
from __future__ import annotations

from offpool_ab_stats import score_fabrication


def test_no_fabrication_when_grounded():
    s = score_fabrication(
        [{"sym": "MKSI", "value": "观察", "note": "x", "dir": 0}],
        near_miss_syms={"MKSI"},
        near_miss_count=1,
    )
    assert s["fabricated_count"] == 0
    assert not s["hard_pad"]


def test_fabrication_when_ungrounded():
    s = score_fabrication(
        [
            {"sym": "MKSI", "value": "观察", "note": "x", "dir": 0},
            {"sym": "SMCI", "value": "多", "note": "y", "dir": 1},
        ],
        near_miss_syms={"MKSI"},
        near_miss_count=1,
    )
    assert s["fabricated_count"] == 1
    assert s["fabricated_syms"] == ["SMCI"]
    assert s["hard_pad"]


def test_padded_to_three():
    s = score_fabrication(
        [{"sym": "A", "dir": 0}, {"sym": "B", "dir": 0}, {"sym": "C", "dir": 0}],
        near_miss_syms={"A"},
        near_miss_count=1,
    )
    assert s["padded_to_three"]
    assert s["hard_pad"]


if __name__ == "__main__":
    test_no_fabrication_when_grounded()
    test_fabrication_when_ungrounded()
    test_padded_to_three()
    print("ok")
