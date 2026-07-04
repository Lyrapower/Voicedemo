#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export JARVIS_TV_WEBHOOK_SECRET=test_secret

python3 - <<'PY'
from jarvis.trading_local_engine import CONFIG_PATH, EVENTS_DIR, FAST_GATE_REPORT_PATH, evaluate_tradingview_payload

original_cfg = CONFIG_PATH.read_text(encoding='utf-8')
cfg = original_cfg.replace('external_signals_enabled: false', 'external_signals_enabled: true')
cfg = cfg.replace('tradingview_webhook_enabled: false', 'tradingview_webhook_enabled: true')
CONFIG_PATH.write_text(cfg, encoding='utf-8')

base = {
    'secret': 'test_secret',
    'source': 'tradingview',
    'ticker': 'MU',
    'timestamp': '2026-04-24T13:35:00Z',
    'price': 128.4,
    'vwap': 127.2,
    'open_range_high': 128.1,
    'rvol': 1.8,
    'signal': 'ORH_VWAP_RVOL_GATE',
    'iv_rank': 48,
}

cases = [
    ('valid MU', base, 'READY_MANUAL_ONLY', []),
    ('TSLA blocked', {**base, 'ticker': 'TSLA'}, 'BLOCKED', ['TICKER_EXCLUDED']),
    ('failed AMD to cash', {**base, 'ticker': 'AMD', 'price': 160.0, 'vwap': 161.0}, 'CASH', ['PRICE_ABOVE_VWAP']),
    ('bad secret', {**base, 'secret': 'wrong_secret'}, 'AUTH_FAILED', ['SECRET_MISMATCH']),
    ('missing field', {k: v for k, v in base.items() if k != 'signal'}, 'INVALID_PAYLOAD', ['MISSING_FIELDS:signal']),
    ('missing iv_rank', {k: v for k, v in base.items() if k != 'iv_rank'}, 'CASH', ['IV_UNKNOWN']),
    ('outside ticker', {**base, 'ticker': 'NBIS'}, 'WATCH', ['OUTSIDE_CORE_POOL']),
]

failed = []
for name, payload, expected_verdict, expected_checks in cases:
    result = evaluate_tradingview_payload(payload)
    if result.get('verdict') != expected_verdict:
        failed.append(f"{name}: expected {expected_verdict}, got {result.get('verdict')}")
    for check in expected_checks:
        if check not in result.get('failed_checks', []):
            failed.append(f"{name}: missing failed_check {check}")

if not FAST_GATE_REPORT_PATH.exists():
    failed.append('FAST_GATE_REPORT.md missing')

event_files = sorted(EVENTS_DIR.glob('*_tradingview_events.jsonl'))
if not event_files:
    failed.append('event jsonl missing')
else:
    latest = event_files[-1]
    content = latest.read_text(encoding='utf-8', errors='ignore')
    if 'test_secret' in content:
        failed.append('secret leaked in event log')

try:
    if failed:
        print('FAIL')
        for item in failed:
            print(f'- {item}')
        raise SystemExit(1)
    print('PASS')
finally:
    CONFIG_PATH.write_text(original_cfg, encoding='utf-8')
PY
