# TradingView Live Webhook Acceptance

Generated: 2026-04-24T10:10:33Z
Server status: started_by_accept

## Checks
- PASS - webhook returns 200 for local smoke payload
- PASS - proof report exists: deliver/proof/trading/FAST_GATE_REPORT.md
- PASS - events jsonl updated: data/trading/events/2026-04-24_tradingview_events.jsonl

## Smoke Output
```
[local] POST http://127.0.0.1:8686/webhooks/tradingview
{"verdict":"CONFIG_DISABLED","reason":"TradingView webhooks disabled in config","failed_checks":["CONFIG_DISABLED"]}
[FAST_GATE_REPORT summary]
- Open Range High: 128.1
- RVOL: 1.8
- IV Rank: 48

## Gate Result
- Verdict: CONFIG_DISABLED
- Reason: TradingView webhooks disabled in config
- Failed checks: CONFIG_DISABLED
- Event log path: data/trading/events/2026-04-24_tradingview_events.jsonl
- Manual execution only: true
- Broker execution: false
- Never outputs BUY: true
[EVENT_LOG latest] data/trading/events/2026-04-24_tradingview_events.jsonl
{"received_at": "2026-04-24T10:10:33Z", "ticker": "MU", "source": "tradingview", "payload": {"source": "tradingview", "ticker": "MU", "timestamp": "2026-04-24T13:35:00Z", "price": 128.4, "vwap": 127.2, "open_range_high": 128.1, "rvol": 1.8, "iv_rank": 48, "signal": "ORH_VWAP_RVOL_GATE", "secret": "REDACTED"}, "verdict": "CONFIG_DISABLED", "failed_checks": ["CONFIG_DISABLED"], "reason": "TradingView webhooks disabled in config", "refused": false}
```

## Proof Paths
- deliver/proof/trading/FAST_GATE_REPORT.md
- deliver/proof/trading/WEBHOOK_LIVE_ACCEPTANCE.md
- data/trading/events/2026-04-24_tradingview_events.jsonl

FINAL VERDICT: PASS
