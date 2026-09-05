"""门禁:生产路径 Alpaca /bars 调用必须带 sort=desc —— 防陈旧K线回归。"""
from __future__ import annotations

import ast
import pathlib
import unittest

from alpaca_bars import BARS_SOURCE_FILES, bars_params, assert_bars_params_safe

ROOT = pathlib.Path(__file__).resolve().parent


def _string_consts(node: ast.AST) -> list[str]:
    out: list[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.append(node.value)
    for ch in ast.iter_child_nodes(node):
        out.extend(_string_consts(ch))
    return out


def _dict_keys(node: ast.AST) -> set[str]:
    keys: set[str] = set()
    if not isinstance(node, ast.Dict):
        return keys
    for k in node.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
    return keys


def _params_has_sort_desc(params_node: ast.AST) -> bool:
    if isinstance(params_node, ast.Call):
        fn = params_node.func
        name = ""
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        if name == "bars_params":
            return True
    if isinstance(params_node, ast.Dict):
        for k, v in zip(params_node.keys, params_node.values):
            if isinstance(k, ast.Constant) and k.value == "sort":
                if isinstance(v, ast.Constant) and str(v.value).lower() == "desc":
                    return True
    return False


class TestAlpacaBarsSortGuard(unittest.TestCase):
    def test_bars_params_helper_forces_desc(self):
        p = bars_params(symbols="PLTR", timeframe="1Min", limit=60)
        self.assertEqual(p["sort"], "desc")
        assert_bars_params_safe(p)
        with self.assertRaises(ValueError):
            assert_bars_params_safe({"symbols": "X", "limit": 2})

    def test_source_files_bars_calls_use_sort_desc(self):
        violations: list[str] = []
        for fname in BARS_SOURCE_FILES:
            if fname == "alpaca_bars.py":
                continue
            path = ROOT / fname
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=fname)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                texts = _string_consts(node)
                params_node = None
                for kw in node.keywords:
                    if kw.arg == "params":
                        params_node = kw.value
                if params_node is None:
                    continue
                keys = _dict_keys(params_node)
                looks_like_bars = any("bars" in t for t in texts) or (
                    {"timeframe", "limit", "feed"} <= keys
                ) or (
                    isinstance(params_node, ast.Call)
                    and (
                        (isinstance(params_node.func, ast.Name) and params_node.func.id == "bars_params")
                        or (isinstance(params_node.func, ast.Attribute) and params_node.func.attr == "bars_params")
                    )
                )
                if not looks_like_bars:
                    continue
                if not _params_has_sort_desc(params_node):
                    violations.append(f"{fname}:{getattr(node, 'lineno', '?')}")
        self.assertEqual(
            violations,
            [],
            "Alpaca bars 调用缺 sort=desc → 会吃旧K线:\n" + "\n".join(violations),
        )

    def test_worker_and_factor_truth_use_bars_params(self):
        for fname in ("worker.py", "factor_truth.py"):
            text = (ROOT / fname).read_text(encoding="utf-8")
            self.assertIn("/stocks/bars", text)
            self.assertIn("bars_params", text)


if __name__ == "__main__":
    unittest.main()
