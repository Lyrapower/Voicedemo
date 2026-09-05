#!/usr/bin/env python3
"""Live smoke: Coinbase/Kraken public feed → paper engine.enter() (no broker)."""
from __future__ import annotations

import json

from paper.account import PaperAccount
from paper import engine as E
from paper.crypto_feed import (
    daily_candles,
    marks,
    spot_price_coinbase,
    spot_price_kraken,
)

SYMS = ["BTC-USD", "ETH-USD", "SOL-USD"]


def main() -> None:
    print("=== Feed probe (US-compliant public APIs) ===")
    for sym in SYMS:
        cb = spot_price_coinbase(sym)
        kr = spot_price_kraken(sym)
        print(f"  {sym}: coinbase={cb} kraken={kr}")

    m_cb = marks(SYMS, prefer="coinbase")
    m_kr = marks(SYMS, prefer="kraken")
    print("\n=== marks coinbase ===", m_cb)
    print("=== marks kraken  ===", m_kr)

    candles = daily_candles("BTC-USD", days=3)
    print("\n=== BTC daily candles (coinbase, last 3) ===")
    if candles:
        for c in candles[-3:]:
            print(f"  close={c['close']} vol={c['volume']}")

    marks_use = m_cb or m_kr
    if not marks_use:
        print("\nFAIL: no live marks")
        return

    print("\n=== Paper enter() smoke (broker_execution=False) ===")
    acc = PaperAccount()
    decisions = []
    # 模拟 aether scan 信号: symbol + want_pct(建议仓位比例) + reason
    signals = [
        ("BTC-USD", 0.15, "paper_smoke: coinbase/kraken mark"),
        ("ETH-USD", 0.50, "paper_smoke: should reject (>20% cap)"),
        ("SOL-USD", 0.10, "paper_smoke: second leg"),
    ]
    for sym, want_pct, reason in signals:
        px = marks_use[sym]
        rec = E.enter(acc, sym, px, want_pct, reason, marks_use)
        decisions.append(rec)
        print(json.dumps(rec, ensure_ascii=False))

    print("\n=== Account ===")
    print("cash", acc.cash, "equity", acc.equity(marks_use), "positions", list(acc.positions))


if __name__ == "__main__":
    main()
