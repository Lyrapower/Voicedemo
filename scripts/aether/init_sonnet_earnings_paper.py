#!/usr/bin/env python3
"""E2 — init sonnet_earnings paper lane + mock NVDA call entry + wallet emit."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "aether-paper"))
sys.path.insert(0, str(ROOT / "aether_nexus"))

from paper.emit import emit_sonnet_earnings_wallet  # noqa: E402
from paper.options_ledger import record_entry, read_trades_summary  # noqa: E402
from paper.store import init_sonnet_earnings_lane, is_lane_initialized  # noqa: E402


def main() -> None:
    if not is_lane_initialized("sonnet_earnings"):
        init_sonnet_earnings_lane(days=30, start_equity=1000.0)
        print("init sonnet_earnings lane")
    summary = read_trades_summary()
    if not summary["open"]:
        record_entry(
            symbol="NVDA",
            strike=210.0,
            expiry="2026-07-17",
            entry_premium=6.40,
            entry_iv=0.34,
            delta=0.42,
            trade_date="2026-07-14",
            earnings_date="2026-07-16",
            meta={"scan": "e2_mock", "contract_type": "call", "qty": 1},
        )
        summary = read_trades_summary()
        print("recorded mock entry NVDA 260717C210")
    ok = emit_sonnet_earnings_wallet(trades_summary=summary)
    print("emit wallet", ok, "open", len(summary["open"]), "breach", summary["discipline_breach_count"])


if __name__ == "__main__":
    main()
