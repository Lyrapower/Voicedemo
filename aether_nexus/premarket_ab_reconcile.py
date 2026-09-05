#!/usr/bin/env python3
"""Premarket A/B post-market reconcile — independent stats per chain, never merge."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aether_shared import EST  # noqa: E402
from premarket_ab_journal import reconcile_chain  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconcile premarket A/B journals (grid vs sonnet, separate)")
    ap.add_argument("--date", help="YYYY-MM-DD (default today EST)")
    ap.add_argument("--outcomes", help="JSON file sym->day_return float")
    ap.add_argument("--fetch", action="store_true", help="Fetch day returns via aether_dryrun")
    args = ap.parse_args()
    trade_date = args.date or dt.datetime.now(EST).date().isoformat()
    outcomes: dict[str, float] = {}
    if args.outcomes:
        outcomes = json.loads(Path(args.outcomes).read_text(encoding="utf-8"))
    elif args.fetch:
        from premarket_ab_journal import JOURNAL_GRID, JOURNAL_SONNET
        from premarket_ab_returns import fetch_day_returns

        syms: set[str] = set()
        for path in (JOURNAL_GRID, JOURNAL_SONNET):
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("date") != trade_date:
                    continue
                sym = str(row.get("sym") or "").upper()
                if sym and sym != "—":
                    syms.add(sym)
        outcomes = fetch_day_returns(trade_date, syms)
    grid = reconcile_chain("grid", trade_date, outcomes=outcomes)
    sonnet = reconcile_chain("sonnet", trade_date, outcomes=outcomes)
    print(json.dumps({"grid": grid, "sonnet": sonnet}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
