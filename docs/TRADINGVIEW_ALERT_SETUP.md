# TradingView Alert Setup for Jarvis Trading v0.4

TradingView does not need to stay open after alerts are created.
Jarvis receiver must stay online.
127.0.0.1 localhost cannot receive TradingView cloud webhooks.
You need a public HTTPS URL via ngrok, Cloudflare Tunnel, or a hosted receiver.

Webhook URL format:
`https://YOUR_PUBLIC_URL/webhooks/tradingview`

## One-time setup
1. Start Jarvis.
2. Expose a public URL.
3. Set `JARVIS_TV_WEBHOOK_SECRET`.
4. Enable `tradingview_webhook_enabled` only when ready.
5. Open MU chart.
6. Add Jarvis Pine indicator.
7. Create Alert.
8. Condition: Jarvis indicator / Any `alert()` function call.
9. Frequency: Once Per Bar Close.
10. Webhook URL: your public URL.
11. Repeat for AMD and IREN.
12. Do not create TSLA alert.

## Daily routine
1. Start Jarvis receiver.
2. Run `bash scripts/daily_trading_check.sh`.
3. Confirm readiness report.
4. Confirm alerts active in TradingView Alert Manager if needed.
5. Do not manually type opening-window fields.
6. Do not upload opening-window CSV.

## How to verify
- `bash scripts/test_tradingview_webhook.sh`
- check `/ui/trading`
- check `deliver/proof/trading/FAST_GATE_REPORT.md`
- check `data/trading/events/`
