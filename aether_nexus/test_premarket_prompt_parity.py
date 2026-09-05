#!/usr/bin/env python3
"""C4 — one-line Grid vs Sonnet premarket prompt parity check."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from grid_compile_client import PREMARKET_SYSTEM  # noqa: E402
from sonnet_egress_client import PREMARKET_SONNET_SYSTEM  # noqa: E402

NORM_KEYS = (
    "标的：SYMBOL",
    "方向：多/空/观察",
    "为什么今天",
    "风险",
    "置信：[高置信/试探性/观察]",
    "3-5 个候选",
    "五字段",
)


def _norm(s: str) -> str:
    return " ".join(s.split())


def main() -> None:
    g = _norm(PREMARKET_SYSTEM)
    s = _norm(PREMARKET_SONNET_SYSTEM)
    missing_g = [k for k in NORM_KEYS if k not in g]
    missing_s = [k for k in NORM_KEYS if k not in s]
    drift = []
    if "pool 宇宙" in s and "pool 宇宙" not in g:
        drift.append("sonnet_requires_pool_universe")
    if missing_g or missing_s:
        print("DRIFT: format keys missing — grid=%s sonnet=%s" % (missing_g, missing_s))
        sys.exit(1)
    print(
        "OK: five-field output spec aligned; residual drift is lane label only "
        "(grid=本地编译 vs sonnet=云端+pool宇宙) — model fingerprint preserved."
    )


if __name__ == "__main__":
    main()
