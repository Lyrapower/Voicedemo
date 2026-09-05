#!/usr/bin/env python3
"""End-of-month (or on-demand) paper behavior audit."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from paper.audit import audit, format_report  # noqa: E402
from paper import equity_feed  # noqa: E402
from paper.store import DECISIONS_PATH, load_account, read_jsonl  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default="", help="YYYY-MM report filename")
    args = parser.parse_args()

    acc = load_account()
    if not acc:
        print("No paper account yet")
        return

    decisions = read_jsonl(DECISIONS_PATH)
    syms = set(acc.positions.keys())
    marks = equity_feed.marks(syms) if syms else {}
    for s, p in acc.positions.items():
        marks.setdefault(s, p.entry_price)
    end_eq = acc.equity(marks)

    report = audit(decisions, acc.start_equity, end_eq)
    text = format_report(report)

    month = args.month or dt.datetime.utcnow().strftime("%Y-%m")
    out = BASE / "reports" / f"{month}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
