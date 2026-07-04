# Trading Daily Readiness Report

Generated: 2026-05-20T04:08:25Z
Verdict: NOT_READY

## Checks
- PASS - config/trading.yaml exists
- PASS - core pool is MU/AMD/IREN (MU,AMD,IREN)
- PASS - TSLA excluded
- PASS - tradingview_webhook_enabled state (false)
- PASS - external_signals_enabled state (false)
- PASS - TRADINGVIEW_WEBHOOK_SECRET present when tunnel/public URL is enabled
- PASS - public_webhook_url set when webhook enabled (MISSING)
- PASS - data/trading/events exists
- PASS - deliver/proof/trading exists
- PASS - docs/TRADINGVIEW_ALERT_SETUP.md exists
- PASS - docs/TRADINGVIEW_PINE_ALERT.md exists
- PASS - tradingview/jarvis_orh_vwap_rvol_gate.pine exists
- PASS - scripts/test_tradingview_webhook.sh exists
- PASS - latest webhook event age (36907 minutes)
- PASS - latest FAST_GATE_REPORT.md (deliver/proof/trading/FAST_GATE_REPORT.md)

## Unknowns
- NONE

## Required User Action
- NONE

- TradingView does not need to stay open after alerts are created
- Jarvis receiver must stay online
- 127.0.0.1 cannot receive TradingView cloud webhooks

FINAL VERDICT: NOT_READY
