"""Unit tests for offpool parse/normalize (no CC CLI calls)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("offpool", ROOT / "aether_offpool_daemon.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["offpool"] = mod
spec.loader.exec_module(mod)


def test_parse_offpool_items_json():
    raw = '{"items":[{"sym":"nvda","value":"多·[试探性]","note":"财报前波动","dir":1}]}'
    items = mod.parse_offpool_items(raw)
    assert len(items) == 1
    assert items[0]["sym"] == "NVDA"
    assert items[0]["dir"] == 1


def test_parse_offpool_codeblock():
    raw = '```json\n{"items":[{"sym":"ASML","note":"supply","dir":-1,"confidence":"观察"}]}\n```'
    items = mod.parse_offpool_items(raw)
    assert items[0]["sym"] == "ASML"
    assert items[0]["dir"] == -1
    assert "观察" in items[0]["value"]


def test_normalize_max_three():
    raw = json.dumps(
        {
            "items": [
                {"sym": "A", "value": "多·[试探性]", "note": "a", "dir": 1},
                {"sym": "B", "value": "空·[观察]", "note": "b", "dir": -1},
                {"sym": "C", "value": "中性·[试探性]", "note": "c", "dir": 0},
                {"sym": "D", "value": "多·[试探性]", "note": "d", "dir": 1},
            ]
        }
    )
    items = mod.parse_offpool_items(raw)
    assert len(items) == 3


if __name__ == "__main__":
    test_parse_offpool_items_json()
    test_parse_offpool_codeblock()
    test_normalize_max_three()
    print("ok")
