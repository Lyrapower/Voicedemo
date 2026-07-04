#!/usr/bin/env bash
# Run all deliverable acceptance scripts and write master report.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
REPORT="$ROOT/deliver/proof/DELIVERABLES_ACCEPTANCE.md"
mkdir -p deliver/proof/aether_watcher deliver/proof/jarvis deliver/proof/crypto

NOW="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
RESULTS=()
FAIL=0

run_accept() {
  local name="$1" cmd="$2"
  set +e
  out=$($cmd 2>&1)
  code=$?
  set -e
  if [ "$code" -eq 0 ]; then
    RESULTS+=("- PASS - $name")
  else
    RESULTS+=("- FAIL - $name")
    FAIL=$((FAIL + 1))
  fi
  RESULTS+=("  \`\`\`")
  RESULTS+=($(echo "$out" | tail -5))
  RESULTS+=("  \`\`\`")
}

chmod +x scripts/accept_aether_watcher.sh scripts/accept_jarvis_automation.sh 2>/dev/null || true

run_accept "Aether Watcher V0.2" "bash scripts/accept_aether_watcher.sh"
run_accept "Jarvis Automation" "bash scripts/accept_jarvis_automation.sh"
run_accept "Crypto v0.3 workbench" "bash scripts/accept_crypto_v0_3.sh"
run_accept "Crypto RWA functional" "bash scripts/accept_crypto_rwa_functional.sh"

VERDICT="PASS"
[ "$FAIL" -gt 0 ] && VERDICT="FAIL"

{
  echo "# Deliverables Master Acceptance"
  echo ""
  echo "Generated: $NOW"
  echo ""
  echo "## Results"
  printf '%s\n' "${RESULTS[@]}"
  echo ""
  echo "## Proof paths"
  echo "- deliver/proof/aether_watcher/ACCEPTANCE_REPORT.md"
  echo "- deliver/proof/jarvis/ACCEPTANCE_REPORT.md"
  echo "- deliver/proof/crypto/ACCEPTANCE_REPORT_v0_3.md"
  echo "- deliver/proof/crypto/ACCEPTANCE_REPORT_RWA_FUNCTIONAL.md"
  echo "- deliver/DELIVERABLES_INDEX.md"
  echo ""
  echo "FINAL VERDICT: $VERDICT"
} > "$REPORT"

echo "FINAL VERDICT: $VERDICT"
echo "$REPORT"
exit $([ "$VERDICT" = "PASS" ] && echo 0 || echo 1)
