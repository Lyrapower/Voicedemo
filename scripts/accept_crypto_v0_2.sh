#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REPORT="deliver/proof/crypto/ACCEPTANCE_REPORT.md"
mkdir -p deliver/proof/crypto

FAILS=()
VERIFIED=()

check_contains() {
  local file="$1"
  local needle="$2"
  local label="$3"
  if [ -f "$file" ] && grep -q "$needle" "$file"; then
    VERIFIED+=("$label")
  else
    FAILS+=("$label :: missing '$needle' in $file")
  fi
}

check_exists() {
  local file="$1"
  local label="$2"
  if [ -f "$file" ]; then
    VERIFIED+=("$label")
  else
    FAILS+=("$label :: missing file $file")
  fi
}

check_exists "templates/workspace.html" "Crypto page/template exists"
check_contains "app/main.py" "Crypto Sovereign AI Infrastructure" "Crypto title set"
check_contains "app/main.py" "A. Landing Hero" "Landing section exists"
check_contains "app/main.py" "B. Why Crypto Is Different" "Why Crypto Is Different exists"
check_contains "app/main.py" "C. Unified Trust Layer" "Trust Layer exists"
check_contains "app/main.py" "Tier 1 - Scopegate Review" "Tier 1 Scopegate Review present"
check_contains "app/main.py" "\$10,000" "Tier 1 price \$10,000 exists"
check_contains "app/main.py" "Tier 2 - Proof Pack Pro" "Tier 2 Proof Pack Pro present"
check_contains "app/main.py" "\$30,000" "Tier 2 price \$30,000 exists"
check_contains "app/main.py" "Tier 3 - Integration Partner / Retainer" "Tier 3 label present"
check_contains "app/main.py" "Starting at \$12,000/month" "Tier 3 price present"
check_contains "app/main.py" "F. Exit Kit Included" "Exit Kit emphasized"
check_contains "app/main.py" "E. Deployment Options" "Deployment Options exists"
check_contains "app/main.py" "Kill switch: one command to disconnect external services" "Kill switch in Trust Layer"
check_contains "app/main.py" "This is a new practice. No inherited client roster" "New practice honest paragraph exists"
check_contains "app/main.py" "Q11: What if you stop operating the business?" "Q11 business continuity exists"
check_contains "templates/workspace.html" "section.kind == \"cta\"" "CTA rendering kind present"
check_contains "app/main.py" "primary_label\": \"Book Scopegate Review\"" "Primary CTA dominance present"

check_exists "deliver/crypto/CUSTOMER_LANDING_COPY.md" "Customer landing doc exists"
check_exists "deliver/crypto/PRICING_TIERS.md" "Pricing doc exists"
check_exists "deliver/crypto/FAQ.md" "FAQ doc exists"
check_exists "deliver/crypto/DEPLOYMENT_OPTIONS.md" "Deployment options doc exists"
check_exists "deliver/crypto/TRUST_LAYER.md" "Trust layer doc exists"

check_exists "deliver/sow/CLIENT_SOW_TEMPLATE.md" "Existing SOW preserved"
check_exists "deliver/deploy/DEPLOY_CHECKLIST.md" "Existing deploy checklist preserved"
check_exists "scripts/deploy_to_client_aws.sh" "Existing deploy stub preserved"
check_exists "deliver/deploy/FICTIONAL_CLIENT_WALKTHROUGH.md" "Existing walkthrough preserved"
check_exists "deliver/demo/END_TO_END_DEMO_FLOW.md" "Existing demo flow preserved"

FAQ_COUNT="$(python3 - <<'PY'
from pathlib import Path
text = Path("deliver/crypto/FAQ.md").read_text(encoding="utf-8", errors="ignore") if Path("deliver/crypto/FAQ.md").exists() else ""
count = sum(1 for line in text.splitlines() if line.strip().startswith("## Q"))
print(count)
PY
)"
if [ "${FAQ_COUNT:-0}" -ge 10 ]; then
  VERIFIED+=("FAQ contains at least 10 Q/A items")
else
  FAILS+=("FAQ count check failed :: found ${FAQ_COUNT:-0}")
fi

DEPLOY_OPTION_COUNT="$(python3 - <<'PY'
from pathlib import Path
text = Path("deliver/crypto/DEPLOYMENT_OPTIONS.md").read_text(encoding="utf-8", errors="ignore") if Path("deliver/crypto/DEPLOYMENT_OPTIONS.md").exists() else ""
count = sum(1 for line in text.splitlines() if line.strip().startswith("## Option "))
print(count)
PY
)"
if [ "${DEPLOY_OPTION_COUNT:-0}" -ge 4 ]; then
  VERIFIED+=("Deployment option count >= 4")
else
  FAILS+=("Deployment option count check failed :: found ${DEPLOY_OPTION_COUNT:-0}")
fi

if grep -R -n -E "fake client logo|guaranteed revenue|regulatory approval|investment returns|fully autonomous trading|we will handle everything" app/main.py deliver/crypto templates/workspace.html >/dev/null 2>&1; then
  FAILS+=("Unsupported/fake guarantee language detected")
else
  VERIFIED+=("No fake client logos or unsupported guarantee language")
fi

if grep -R -n -E -i "wallet/key custody|wallet custody|private keys|seed phrases|does not provide legal|legal, regulatory, tax, or compliance opinions" app/main.py deliver/crypto >/dev/null 2>&1; then
  VERIFIED+=("No wallet/private key custody claim and no legal/compliance advice claim")
else
  FAILS+=("Custody/compliance boundary language missing")
fi

NOW_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
FINAL="PASS"
if [ "${#FAILS[@]}" -gt 0 ]; then
  FINAL="FAIL"
fi
KILL_SWITCH_MENTIONED="no"
for item in "${VERIFIED[@]}"; do
  if [ "$item" = "Kill switch in Trust Layer" ]; then
    KILL_SWITCH_MENTIONED="yes"
    break
  fi
done

{
  echo "# Crypto v0.2 Customer-Facing Acceptance Report"
  echo
  echo "generated_at: ${NOW_UTC}"
  echo "module: crypto_v0.2_customer_facing"
  echo "final_verdict: ${FINAL}"
  echo
  echo "## verified sections"
  for item in "${VERIFIED[@]}"; do
    echo "- ${item}"
  done
  echo
  echo "## pricing tiers"
  echo "- Tier 1 - Scopegate Review: \$10,000"
  echo "- Tier 2 - Proof Pack Pro: \$30,000"
  echo "- Tier 3 - Integration Partner / Retainer: Starting at \$12,000/month"
  echo
  echo "## trust layer status"
  echo "- status: $([ "$FINAL" = "PASS" ] && echo verified || echo needs_review)"
  echo "- kill_switch_mentioned: ${KILL_SWITCH_MENTIONED}"
  echo
  echo "## faq count"
  echo "- ${FAQ_COUNT}"
  echo
  echo "## deployment option count"
  echo "- ${DEPLOY_OPTION_COUNT}"
  echo
  echo "## proof paths"
  echo "- deliver/crypto/CUSTOMER_LANDING_COPY.md"
  echo "- deliver/crypto/PRICING_TIERS.md"
  echo "- deliver/crypto/FAQ.md"
  echo "- deliver/crypto/DEPLOYMENT_OPTIONS.md"
  echo "- deliver/crypto/TRUST_LAYER.md"
  echo "- deliver/proof/crypto/ACCEPTANCE_REPORT.md"
  echo
  echo "## failed checks"
  if [ "${#FAILS[@]}" -eq 0 ]; then
    echo "- NONE"
  else
    for item in "${FAILS[@]}"; do
      echo "- ${item}"
    done
  fi
} > "$REPORT"

if [ "$FINAL" = "PASS" ]; then
  exit 0
fi
exit 1
