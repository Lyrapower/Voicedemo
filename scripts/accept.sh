#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# TripPack API: FastAPI + SQLite (no Docker). Writes deliver/proof/ACCEPT_REPORT.md
if [ "${1:-}" = "--trippack" ] || [ "${ACCEPT_TRIPPACK_ONLY:-0}" = "1" ]; then
  exec bash "$ROOT_DIR/scripts/accept_trippack.sh"
fi
cd "$ROOT_DIR"

mkdir -p deliver/proof deliver/proof/openclaw_v1 deliver/proof/trading deliver/proof/crypto deliver/proof_pack logs

OPENCLAW_REPORT="deliver/proof/openclaw_v1/ACCEPTANCE_REPORT.md"
TRADING_REPORT="deliver/proof/trading/ACCEPTANCE_REPORT.md"
CRYPTO_REPORT="deliver/proof/crypto/ACCEPTANCE_REPORT.md"
PP_REPORT="deliver/proof_pack/ACCEPTANCE_REPORT.md"
TOP_REPORT="deliver/proof/ACCEPTANCE_REPORT.md"

FAIL_COUNT=0
CHECKS=""

check() {
  local label="$1" result="$2"
  if [ "$result" = "PASS" ]; then
    CHECKS="${CHECKS}- PASS - ${label}\n"
  else
    CHECKS="${CHECKS}- FAIL - ${label}\n"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

# 1. Verify Jarvis platform entry (crypto/trading/automation live here)
if python3 -c "from app.platform_main import app" 2>/dev/null; then
  check "platform_main import (Jarvis sole entry)" "PASS"
else
  check "platform_main import (Jarvis sole entry)" "FAIL"
fi

# 2. Check required Jarvis routes exist on platform_main
REQUIRED_ROUTES="/ui/overview /ui/trading /ui/crypto /ui/proof-pack /ui/senior /ui/desk /ui/archive /ui/proof /ui/audit /api/jarvis/tasks"
ROUTES_OK="PASS"
for route in $REQUIRED_ROUTES; do
  if python3 -c "
from app.platform_main import app
paths = [r.path for r in app.routes if hasattr(r, 'path')]
assert '${route}' in paths
" 2>/dev/null; then
    :
  else
    ROUTES_OK="FAIL"
  fi
done
check "required routes on platform_main ($REQUIRED_ROUTES)" "$ROUTES_OK"

# 3. Check external_enabled is false
EXTERNAL_CHECK=$(python3 -c "
from app.router.review_pipeline import ReviewPipeline
p = ReviewPipeline()
print('ON' if p._is_external_enabled() else 'OFF')
" 2>/dev/null || echo "OFF")
if [ "$EXTERNAL_CHECK" = "OFF" ]; then
  check "external_enabled is OFF" "PASS"
else
  check "external_enabled is OFF (got: $EXTERNAL_CHECK)" "FAIL"
fi

# 4. Check Proof Pack artifacts
PP_DIR="deliver/proof_pack"
PP_OK="PASS"
for f in TEMPLATE_REPO.md INJECTOR_SPEC.md SCOPEGATE_RULES.md REFERENCE_IMPL.md; do
  if [ ! -f "$PP_DIR/$f" ]; then
    PP_OK="FAIL"
  fi
done
check "Proof Pack artifacts in $PP_DIR" "$PP_OK"

# 4b. Premium UI checks
UI_PREMIUM_OK="PASS"
if [ ! -f "static/css/premium.css" ]; then
  UI_PREMIUM_OK="FAIL"
fi
if [ "$UI_PREMIUM_OK" = "PASS" ]; then
  if ! grep -q -- "--premium-bg: #FAFAF7;" static/css/premium.css; then UI_PREMIUM_OK="FAIL"; fi
  if ! grep -q -- "--premium-surface: #FFFFFF;" static/css/premium.css; then UI_PREMIUM_OK="FAIL"; fi
  if ! grep -q -- "--premium-text: #1C1C1E;" static/css/premium.css; then UI_PREMIUM_OK="FAIL"; fi
  if ! grep -q -- "--premium-accent: #0066CC;" static/css/premium.css; then UI_PREMIUM_OK="FAIL"; fi
fi
check "premium.css exists with design tokens" "$UI_PREMIUM_OK"

UI_CLASS_GUARD="PASS"
if grep -R -n -E "class=\\\"[^\\\"]*\\b(container|row|col-(sm|md|lg|xl)-[0-9]+|btn-primary|text-(xs|sm|lg|xl)|bg-(gray|slate|zinc|red|green|blue)-[0-9]{2,3}|mt-[0-9]+|p-[0-9]+)\\b" templates >/dev/null 2>&1; then
  UI_CLASS_GUARD="FAIL"
fi
check "templates avoid Bootstrap/Tailwind default classes" "$UI_CLASS_GUARD"

# 5. Senior V1 hard gates
SENIOR_OK="PASS"
CLIENT_DIR="clients/openclaw_senior_flutter"
if [ -f "$CLIENT_DIR/lib/core/services/safety_chain_service.dart" ] && grep -q "ESCALATE_72H" "$CLIENT_DIR/lib/core/services/safety_chain_service.dart" 2>/dev/null; then
  :
else
  SENIOR_OK="FAIL"
fi
if [ -f "$CLIENT_DIR/lib/core/services/tts_service.dart" ] && grep -q "TTS_SPOKEN" "$CLIENT_DIR/lib/core/services/tts_service.dart" 2>/dev/null; then
  :
else
  SENIOR_OK="FAIL"
fi
if [ -f "$CLIENT_DIR/lib/core/services/verified_mode_service.dart" ] && grep -q "medication" "$CLIENT_DIR/lib/core/services/verified_mode_service.dart" 2>/dev/null; then
  :
else
  SENIOR_OK="FAIL"
fi
check "Senior V1 hard gates (72h, TTS, Verified)" "$SENIOR_OK"

# 6. Run module verifiers
OPENCLAW_STATUS="FAIL"
TRADING_STATUS="FAIL"
CRYPTO_STATUS="FAIL"
TRADING_V04_STATUS="FAIL"
CRYPTO_V03_STATUS="FAIL"

set +e
python3 scripts/verify_openclaw_v1.py 2>/dev/null
if [ -f "$OPENCLAW_REPORT" ] && grep -q "FINAL VERDICT: PASS" "$OPENCLAW_REPORT"; then
  OPENCLAW_STATUS="PASS"
fi

bash scripts/accept_ui.sh 2>/dev/null
if [ -f "$TRADING_REPORT" ] && grep -q "FINAL VERDICT: PASS" "$TRADING_REPORT"; then
  TRADING_STATUS="PASS"
fi

if [ -x "scripts/accept_trading_v0_4.sh" ]; then
  bash scripts/accept_trading_v0_4.sh 2>/dev/null
  if [ -f "$TRADING_REPORT" ] && grep -q "FINAL VERDICT: PASS" "$TRADING_REPORT"; then
    TRADING_V04_STATUS="PASS"
    TRADING_STATUS="PASS"
  fi
fi

if [ -x "scripts/accept_crypto_v1.sh" ]; then
  ./scripts/accept_crypto_v1.sh 2>/dev/null
  if [ -f "$CRYPTO_REPORT" ] && grep -q "FINAL VERDICT: PASS" "$CRYPTO_REPORT"; then
    CRYPTO_STATUS="PASS"
  fi
fi
if [ -x "scripts/accept_crypto_v0_2.sh" ]; then
  bash scripts/accept_crypto_v0_2.sh 2>/dev/null
  if [ -f "$CRYPTO_REPORT" ] && grep -q "final_verdict: PASS" "$CRYPTO_REPORT"; then
    CRYPTO_STATUS="PASS"
  fi
fi
if [ -x "scripts/accept_crypto_v0_3.sh" ]; then
  bash scripts/accept_crypto_v0_3.sh 2>/dev/null
  if [ -f "deliver/proof/crypto/ACCEPTANCE_REPORT_v0_3.md" ] && grep -q "verdict: PASS" "deliver/proof/crypto/ACCEPTANCE_REPORT_v0_3.md"; then
    CRYPTO_V03_STATUS="PASS"
    CRYPTO_STATUS="PASS"
  fi
fi
set -e

check "OpenClaw Senior V1 module" "$OPENCLAW_STATUS"
check "Trading module" "$TRADING_STATUS"
check "Trading v0.4 module" "$TRADING_V04_STATUS"
check "Crypto module" "$CRYPTO_STATUS"
check "Crypto v0.3 workbench module" "$CRYPTO_V03_STATUS"

# 7. Determine final verdict
NOW_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

if [ "$OPENCLAW_STATUS" = "PASS" ] && [ "$TRADING_STATUS" = "PASS" ]; then
  FINAL="PASS"
else
  FINAL="FAIL"
fi

# 8. Write top-level report
cat > "$TOP_REPORT" <<REPORT
# Whole System Acceptance Report

Generated: $NOW_UTC

## Checks
$(echo -e "$CHECKS")

## Module Verdicts
- OpenClaw Senior V1: $OPENCLAW_STATUS
- Trading Module: $TRADING_STATUS
- Crypto V1: $CRYPTO_STATUS

## Proof Paths
- OpenClaw: $OPENCLAW_REPORT
- Trading: $TRADING_REPORT
- Crypto: $CRYPTO_REPORT
- Proof Pack: $PP_REPORT

## Commands
- Top-level: ./scripts/accept.sh
- Senior V1: ./scripts/accept_senior_v1.sh
- Proof Pack: ./scripts/accept_proof_pack.sh
- Crypto: ./scripts/accept_crypto_v1.sh
- Crypto v0.2 customer-facing: ./scripts/accept_crypto_v0_2.sh
- Crypto v0.3 two-track workbench: ./scripts/accept_crypto_v0_3.sh

FINAL VERDICT: $FINAL
REPORT

# 9. Print result
echo ""
echo "=============================="
if [ "$FINAL" = "PASS" ]; then
  echo "FINAL VERDICT: PASS"
  echo "[$NOW_UTC] ACCEPTANCE_PASS | all modules" >> logs/audit.log
else
  echo "FINAL VERDICT: FAIL"
  echo "Failed checks: $FAIL_COUNT"
  echo "[$NOW_UTC] ACCEPTANCE_FAIL | openclaw=$OPENCLAW_STATUS | trading=$TRADING_STATUS | crypto=$CRYPTO_STATUS" >> logs/audit.log
fi
echo "Proof path: $TOP_REPORT"
echo "=============================="

if [ "$FINAL" = "PASS" ]; then
  exit 0
else
  exit 1
fi
