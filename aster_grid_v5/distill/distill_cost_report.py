#!/usr/bin/env python3
"""Distill cost report — reads distill_records.jsonl (spec v1 §6)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME = _ROOT / "grid-sovereign-runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

from field_lane.distill_record import DAILY_CAP, fable_calls_on_date, load_records  # noqa: E402


def report(*, on_date: str | None = None) -> dict:
    day = on_date or dt.date.today().isoformat()
    rows = load_records(on_date=day)
    calls = fable_calls_on_date(day)
    skips = sum(1 for r in rows if r.get("skip_reason") == "budget")
    cost = 0.0
    for r in rows:
        meta = r.get("cli_meta") or {}
        c = meta.get("cost_usd")
        if c is not None:
            cost += float(c)
    remaining = max(0, DAILY_CAP - calls)
    return {
        "date": day,
        "fable_calls": calls,
        "budget_skips": skips,
        "estimated_cost_usd": round(cost, 4),
        "daily_cap": DAILY_CAP,
        "cap_remaining": remaining,
        "at_cap": calls >= DAILY_CAP,
        "record_count": len(rows),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Distill daily cost / cap report")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data = report(on_date=args.date)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(
            f"{data['date']} | calls={data['fable_calls']}/{data['daily_cap']} "
            f"| est=${data['estimated_cost_usd']:.4f} | skips={data['budget_skips']} "
            f"| remaining={data['cap_remaining']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
