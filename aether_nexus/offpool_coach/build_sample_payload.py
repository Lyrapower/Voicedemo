#!/usr/bin/env python3
"""Emit a real offpool_coach payload sample from rejection logs."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from offpool_coach.stage2_payload_builder import build_payload, write_sample  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Build offpool_coach payload sample JSON")
    ap.add_argument("--date", help="YYYY-MM-DD (default today EST)")
    ap.add_argument("--window", choices=("PREMARKET", "EXECUTION"), default="PREMARKET")
    ap.add_argument(
        "--out",
        help="Output path (default offpool_coach/samples/payload_{window}_{date}.json)",
    )
    args = ap.parse_args()

    import datetime as dt

    from aether_shared import EST

    trade_date = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(EST).date()
    payload = build_payload(window=args.window, trade_date=trade_date, staleness_anchor="scan_plus")
    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parent
        / "samples"
        / f"payload_{args.window}_{trade_date.isoformat()}.json"
    )
    write_sample(out, payload)
    print(out)
    print(f"candidates={len(payload.get('candidates') or [])}")


if __name__ == "__main__":
    main()
