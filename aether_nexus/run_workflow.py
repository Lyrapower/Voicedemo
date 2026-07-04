#!/usr/bin/env python3
"""Headless Aether Nexus workflow — connect, scan, buy check, monitor."""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

if os.getenv("MOCK_IB", "false").lower() == "true":
    os.environ.setdefault("TRADING_START", "00:00")
    os.environ.setdefault("TRADING_END", "23:59")

from aether_nexus import MOCK_IB, create_broker, TradingEngine  # noqa: E402


def main() -> int:
    broker = create_broker()
    engine = TradingEngine(broker)

    print(f"Mode: {'MOCK_IB' if MOCK_IB else 'LIVE IB'}")
    print("Step 1/4: Connecting to IB...")
    if not broker.connect():
        print("ERROR: IB connection failed. Start TWS/Gateway or set MOCK_IB=true.", file=sys.stderr)
        return 1
    print("  Connected.")

    print("Step 2/4: S&P 500 scan...")
    candidates = engine.pre_market_screen()
    print(f"  Candidates: {candidates}")
    print(f"  Scan timestamp: {engine.scan_timestamp}")

    print("Step 3/4: Check buy signals...")
    engine.check_and_buy()
    positions = engine.get_positions()
    print(f"  Positions after buy check: {len(positions)}")

    print("Step 4/4: Monitor positions...")
    engine.monitor_positions()

    print("\n--- Agent log (last 15) ---")
    for line in engine.logs[-15:]:
        print(line)

    print("\n--- Order audit (last 5) ---")
    for row in engine.order_audit_log[-5:]:
        print(row)

    broker.disconnect()
    print("\nWorkflow complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
