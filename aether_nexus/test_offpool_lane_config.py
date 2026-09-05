"""Unit tests for off-pool lane registry."""
from __future__ import annotations

import os

from offpool_lane_config import OffpoolLane, default_offpool_lanes


def test_legacy_colon_lane_parses_as_cc_cli(monkeypatch):
    monkeypatch.setenv("OFFPOOL_LANES", "sonnet-4.6:claude-sonnet-4-6:SONNET 4.6")
    lanes = default_offpool_lanes()
    assert len(lanes) == 1
    assert lanes[0] == OffpoolLane("sonnet-4.6", "cc_cli", "claude-sonnet-4-6", "SONNET 4.6")


def test_pipe_lanes_parse_deepseek(monkeypatch):
    monkeypatch.setenv(
        "OFFPOOL_LANES",
        "sonnet-4.6|cc_cli|claude-sonnet-4-6|SONNET 4.6,"
        "deepseek-v4|ollama_cloud|deepseek-v4-flash:cloud|DEEPSEEK V4",
    )
    lanes = default_offpool_lanes()
    assert [l.lane for l in lanes] == ["sonnet-4.6", "deepseek-v4"]
    assert lanes[1].backend == "ollama_cloud"
    assert lanes[1].model == "deepseek-v4-flash:cloud"


def test_default_lanes_include_both_when_unset(monkeypatch):
    monkeypatch.delenv("OFFPOOL_LANES", raising=False)
    lanes = default_offpool_lanes()
    assert [l.lane for l in lanes] == ["sonnet-4.6", "deepseek-v4"]


if __name__ == "__main__":
    test_legacy_colon_lane_parses_as_cc_cli(type("M", (), {"setenv": os.environ.__setitem__, "delenv": os.environ.pop})())
    print("ok")
