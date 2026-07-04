#!/usr/bin/env python3
"""Regenerate knowledge/compiled/*.md including WORKSPACE_trading Bottleneck Ledger."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.router.compiled_memory import (  # noqa: E402
    BOTTLENECK_LEDGER_HEADER,
    TRADING_PERMISSION_LINE,
    build_compiled_memory,
)


def _extract_bottleneck_ledger(text: str) -> str:
    if BOTTLENECK_LEDGER_HEADER not in text:
        return ""
    start = text.index(BOTTLENECK_LEDGER_HEADER)
    end = text.index(TRADING_PERMISSION_LINE, start)
    return text[start:end].rstrip()


def main() -> int:
    paths = build_compiled_memory()
    trading = ROOT / "knowledge" / "compiled" / "WORKSPACE_trading.md"
    body = trading.read_text(encoding="utf-8")
    section = _extract_bottleneck_ledger(body)
    print(section, flush=True)
    print(flush=True)
    print(TRADING_PERMISSION_LINE, flush=True)
    for p in paths:
        print(p.relative_to(ROOT), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
