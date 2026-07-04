#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p deliver/proof/trading data/trading/events

python3 jarvis/trading_local_engine.py >/dev/null
bash scripts/daily_trading_check.sh >/dev/null
bash scripts/test_tradingview_webhook.sh >/dev/null

python3 - <<'PY'
from pathlib import Path
from jarvis.trading_local_engine import write_acceptance_report

root = Path(".")
checks = []

def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))

cfg = root / "config" / "trading.yaml"
engine = root / "jarvis" / "trading_local_engine.py"
doc_setup = root / "docs" / "TRADINGVIEW_ALERT_SETUP.md"
doc_pine = root / "docs" / "TRADINGVIEW_PINE_ALERT.md"
pine = root / "tradingview" / "jarvis_orh_vwap_rvol_gate.pine"
daily = root / "scripts" / "daily_trading_check.sh"
test = root / "scripts" / "test_tradingview_webhook.sh"
fast = root / "deliver" / "proof" / "trading" / "FAST_GATE_REPORT.md"
readiness = root / "deliver" / "proof" / "trading" / "DAILY_READINESS_REPORT.md"
accept = root / "deliver" / "proof" / "trading" / "ACCEPTANCE_REPORT.md"
workspace = root / "templates" / "workspace.html"

check("config/trading.yaml exists", cfg.exists())
check("jarvis/trading_local_engine.py exists", engine.exists())
check("docs/TRADINGVIEW_ALERT_SETUP.md exists", doc_setup.exists())
check("docs/TRADINGVIEW_PINE_ALERT.md exists", doc_pine.exists())
check("tradingview/jarvis_orh_vwap_rvol_gate.pine exists", pine.exists())
check("scripts/daily_trading_check.sh exists", daily.exists())
check("scripts/test_tradingview_webhook.sh exists", test.exists())
check("FAST_GATE_REPORT.md exists", fast.exists())
check("DAILY_READINESS_REPORT.md exists", readiness.exists())
check("ACCEPTANCE_REPORT.md exists", accept.exists())

event_files = sorted((root / "data" / "trading" / "events").glob("*_tradingview_events.jsonl"))
check("event jsonl exists after test", bool(event_files))

cfg_text = cfg.read_text(encoding="utf-8", errors="ignore") if cfg.exists() else ""
check("MU/AMD/IREN exist in config", all(x in cfg_text for x in ["MU", "AMD", "IREN"]))
check("TSLA excluded", "excluded" in cfg_text and "TSLA" in cfg_text)
check("72h retention exists", "upload_retention_hours: 72" in cfg_text)

engine_text = engine.read_text(encoding="utf-8", errors="ignore") if engine.exists() else ""
buy_impl_tokens = ['"verdict": "BUY"', "'verdict': 'BUY'"]
check("no BUY verdict implementation exists", not any(tok in engine_text for tok in buy_impl_tokens))
check("no broker execution code exists", "broker_execution: false" in cfg_text and "execute order" not in engine_text.lower())

secret_leak = False
for path in event_files[-3:]:
    if "test_secret" in path.read_text(encoding="utf-8", errors="ignore"):
        secret_leak = True
check("no secret appears in event logs", not secret_leak)

ws_text = workspace.read_text(encoding="utf-8", errors="ignore") if workspace.exists() else ""
check("UI/template contains TradingView Webhook Gate", "TradingView Webhook Gate" in ws_text)
check("UI/template contains Daily Readiness", "Daily Readiness" in ws_text)

verdict = write_acceptance_report(checks)
print(verdict)
PY
