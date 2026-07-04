# TradingView Webhook Live (Port 8686)

Jarvis endpoint:
- `POST /webhooks/tradingview`
- Full path when exposed: `https://YOUR_PUBLIC_DOMAIN/webhooks/tradingview`

Security contract:
- Secret transport: **JSON payload field** `secret`
- Env required for public/tunnel mode: `TRADINGVIEW_WEBHOOK_SECRET`
- If secret is missing/wrong in secured mode, Jarvis returns `401` and writes a refusal event to `data/trading/events/*_tradingview_events.jsonl`
- Do not expose public ingress without setting `TRADINGVIEW_WEBHOOK_SECRET`

## Option A: ngrok quick start

1. Start Jarvis on `127.0.0.1:8686`
2. Run:
   - `bash scripts/tv_tunnel_ngrok.sh`
3. Copy printed `PUBLIC_WEBHOOK_URL=.../webhooks/tradingview`
4. Export for local tooling:
   - `export PUBLIC_WEBHOOK_URL="https://xxxx.ngrok-free.app"`

## Option B: cloudflared (recommended for stable workflows)

1. Start Jarvis on `127.0.0.1:8686`
2. Run:
   - `bash scripts/tv_tunnel_cloudflared.sh`
3. Copy printed `PUBLIC_WEBHOOK_URL=.../webhooks/tradingview`
4. Export for local tooling:
   - `export PUBLIC_WEBHOOK_URL="https://xxxx.trycloudflare.com"`

## TradingView Alert Configuration

- Condition: `Jarvis ORH VWAP RVOL Gate` -> `Any alert() function call`
- Frequency: `Once Per Bar Close`
- Webhook URL: `https://YOUR_PUBLIC_DOMAIN/webhooks/tradingview`
- Message JSON:

```json
{
  "secret": "YOUR_TRADINGVIEW_WEBHOOK_SECRET",
  "source": "tradingview",
  "ticker": "{{ticker}}",
  "timestamp": "{{timenow}}",
  "price": {{close}},
  "vwap": {{plot_0}},
  "open_range_high": {{plot_1}},
  "rvol": 1.8,
  "iv_rank": 48,
  "signal": "ORH_VWAP_RVOL_GATE"
}
```

## One-command acceptance

1. Set secret:
   - `export TRADINGVIEW_WEBHOOK_SECRET="change_me"`
2. Run:
   - `./accept.sh`

Proof artifacts:
- `deliver/proof/trading/FAST_GATE_REPORT.md`
- `deliver/proof/trading/WEBHOOK_LIVE_ACCEPTANCE.md`
- `data/trading/events/*_tradingview_events.jsonl`

## Troubleshooting

- `401 AUTH_FAILED`: secret missing/mismatch. Verify `TRADINGVIEW_WEBHOOK_SECRET` and payload `secret`.
- `404 Not Found`: wrong path; must be `/webhooks/tradingview`.
- `5xx`: Jarvis not running on `127.0.0.1:8686` or crashed.
- TradingView alert not firing: verify alert condition, alert enabled, and webhook URL still active.
