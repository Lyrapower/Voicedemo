#!/usr/bin/env python3
"""S1 — print dual bootstrap verdict report (warmup-aware)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "aether_nexus"))

from premarket_verdict_bootstrap import dual_verdict_report  # noqa: E402
from premarket_ab_scoring import compute_dual_leaderboard  # noqa: E402


def main() -> int:
    report = dual_verdict_report()
    board = compute_dual_leaderboard()
    out = {"verdict_bootstrap": report, "dual_leaderboard": board}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
