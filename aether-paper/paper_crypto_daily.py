#!/usr/bin/env python3
"""Daily crypto momentum signals → crypto paper inbox (US public feeds only)."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from paper.crypto_signals import generate_daily_signals  # noqa: E402
from paper.store import append_jsonl, lane_paths, load_processed  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("paper_crypto_daily")


def run(*, day: str | None = None) -> int:
    paths = lane_paths("crypto_rules")
    processed = load_processed(lane="crypto_rules")
    signals = generate_daily_signals(day=day)
    n = 0
    for sig in signals:
        key = sig.get("key", "")
        if key in processed:
            continue
        append_jsonl(paths["inbox"], sig)
        n += 1
        logger.info("enqueued %s want=%.0f%% ret_score=%s", sig["symbol"], sig["want_pct"] * 100, sig.get("score"))
    logger.info("crypto daily done: %d new signals (universe scan %d)", n, len(signals))
    return n


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default="", help="UTC day YYYY-MM-DD override")
    args = parser.parse_args()
    run(day=args.day or None)


if __name__ == "__main__":
    main()
