#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PP_DIR="$ROOT/deliver/proof_pack"
REPORT="$PP_DIR/ACCEPTANCE_REPORT.md"
FAIL=0
CHECKS=""

required_files=(
  "TEMPLATE_REPO.md"
  "INJECTOR_SPEC.md"
  "SCOPEGATE_RULES.md"
  "REFERENCE_IMPL.md"
)

for f in "${required_files[@]}"; do
  if [ -f "$PP_DIR/$f" ]; then
    CHECKS="${CHECKS}- PASS - $f exists\n"
  else
    CHECKS="${CHECKS}- FAIL - $f missing\n"
    FAIL=1
  fi
done

if [ "$FAIL" -eq 0 ]; then
  VERDICT="PASS"
else
  VERDICT="FAIL"
fi

cat > "$REPORT" <<EOF
# Proof Pack Acceptance Report
Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')

$(echo -e "$CHECKS")

FINAL VERDICT: $VERDICT
EOF

echo ""
echo "Proof Pack Acceptance: $VERDICT"
echo "Report: $REPORT"
