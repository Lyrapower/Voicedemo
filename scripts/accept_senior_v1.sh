#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPORT_DIR="$ROOT/deliver/proof/openclaw_v1"
REPORT="$REPORT_DIR/ACCEPTANCE_REPORT.md"
FAIL=0
CHECKS=""

mkdir -p "$REPORT_DIR"

if python3 "$ROOT/scripts/verify_openclaw_v1.py" 2>/dev/null; then
  CHECKS="${CHECKS}- PASS - verify_openclaw_v1.py passed\n"
else
  CHECKS="${CHECKS}- FAIL - verify_openclaw_v1.py failed\n"
  FAIL=1
fi

CLIENT="$ROOT/clients/openclaw_senior_flutter"
hard_gates=(
  "lib/core/services/safety_chain_service.dart:ESCALATE_72H"
  "lib/core/services/tts_service.dart:TTS_SPOKEN"
  "lib/core/services/verified_mode_service.dart:medication"
)

for gate in "${hard_gates[@]}"; do
  FILE="${gate%%:*}"
  TOKEN="${gate##*:}"
  if [ -f "$CLIENT/$FILE" ] && grep -q "$TOKEN" "$CLIENT/$FILE" 2>/dev/null; then
    CHECKS="${CHECKS}- PASS - $FILE contains $TOKEN\n"
  else
    CHECKS="${CHECKS}- FAIL - $FILE missing $TOKEN\n"
    FAIL=1
  fi
done

if [ "$FAIL" -eq 0 ]; then
  VERDICT="PASS"
else
  VERDICT="FAIL"
fi

cat > "$REPORT" <<EOF
# Senior V1 Acceptance Report
Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')

$(echo -e "$CHECKS")

FINAL VERDICT: $VERDICT
EOF

echo ""
echo "Senior V1 Acceptance: $VERDICT"
echo "Report: $REPORT"
