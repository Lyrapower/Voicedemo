"""Alpha Factory df schema contract loader (Phase 0 pinned · fix_error grey-zone source)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_SCHEMA_CANDIDATES = (
    Path(__file__).resolve().parent / "schemas" / "factory_df_contract.json",
    Path(__file__).resolve().parent.parent / "schemas" / "factory_df_contract.json",
)


_COLUMN_IN_ERR = re.compile(
    r"(?:KeyError|ColumnNotFoundError|column)\s*[:\s]*['\"]([^'\"]+)['\"]",
    re.I,
)


def _schema_path() -> Path:
    for p in _SCHEMA_CANDIDATES:
        if p.is_file():
            return p
    raise FileNotFoundError(f"factory df contract missing; tried: {_SCHEMA_CANDIDATES}")


@lru_cache(maxsize=1)
def load_contract() -> dict[str, Any]:
    return json.loads(_schema_path().read_text(encoding="utf-8"))


def column_whitelist() -> frozenset[str]:
    c = load_contract()
    return frozenset(str(x) for x in c.get("column_whitelist") or [])


def schema_hint_text() -> str:
    c = load_contract()
    cols = ", ".join(c.get("column_whitelist") or [])
    idx = c.get("index") or {}
    uni = c.get("universe") or {}
    return (
        f"输入 DataFrame 列(白名单): {cols}。"
        f"index: {idx.get('note', '任意')}。"
        f"universe: {uni.get('delivery', 'df 内 symbol 列')}。"
        f"缺失值: {c.get('missing_values', 'worker 不填充')}。"
    )


def template_comment_block() -> str:
    c = load_contract()
    lines = c.get("template_comment") or []
    return "\n".join(str(x) for x in lines)


def columns_referenced_in_error(err: str) -> set[str]:
    return {m.group(1) for m in _COLUMN_IN_ERR.finditer(err or "")}


def is_off_schema_column(col: str) -> bool:
    return col not in column_whitelist()


def classify_column_error(err: str) -> str:
    """Return 'factor_code' if any referenced column is off-schema; else 'pipeline'."""
    refs = columns_referenced_in_error(err)
    if not refs:
        return "factor_code"
    if any(is_off_schema_column(c) for c in refs):
        return "factor_code"
    return "pipeline"
