#!/usr/bin/env python3
"""KeepAlive watchdog — auto-runs missed daily lanes (no manual health checks)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import time

from schedule_catchup import catchup_pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("schedule_catchup_daemon")


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto catch-up for missed Aether daily slots")
    ap.add_argument("--once", action="store_true", help="Single sweep then exit")
    ap.add_argument("--loop", action="store_true", help="Poll until interrupted")
    args = ap.parse_args()

    interval = int(os.getenv("SCHEDULE_CATCHUP_POLL_SEC", "120"))

    if args.once or not args.loop:
        result = catchup_pass()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    logger.info("schedule catchup daemon | poll=%ds", interval)
    while True:
        try:
            result = catchup_pass()
            if result.get("actions"):
                logger.info("catchup actions: %s", json.dumps(result["actions"], ensure_ascii=False))
        except Exception:
            logger.exception("catchup pass failed")
        time.sleep(interval)


if __name__ == "__main__":
    main()
