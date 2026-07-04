#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p deliver/proof/crypto
mkdir -p logs
REPORT="deliver/proof/crypto/ACCEPTANCE_REPORT.md"
NOW_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

required_paths=(
  "deliver/sow/CLIENT_SOW_TEMPLATE.md"
  "deliver/deploy/DEPLOY_CHECKLIST.md"
  "scripts/deploy_to_client_aws.sh"
)

pass=true
missing=()
for path in "${required_paths[@]}"; do
  if [[ ! -f "$path" ]]; then
    pass=false
    missing+=("$path")
  fi
done

walkthrough_found="NO"
if find . -type f \( -iname '*walkthrough*.md' -o -iname '*demo*flow*.md' -o -iname '*fictional*client*.md' \) | grep -q .; then
  walkthrough_found="YES"
else
  pass=false
fi

cat > "$REPORT" <<REPORT
# Crypto V1 Acceptance Report

Generated: $NOW_UTC

## Required Artifacts
- deliver/sow/CLIENT_SOW_TEMPLATE.md: $( [[ -f deliver/sow/CLIENT_SOW_TEMPLATE.md ]] && echo PASS || echo FAIL )
- deliver/deploy/DEPLOY_CHECKLIST.md: $( [[ -f deliver/deploy/DEPLOY_CHECKLIST.md ]] && echo PASS || echo FAIL )
- scripts/deploy_to_client_aws.sh: $( [[ -f scripts/deploy_to_client_aws.sh ]] && echo PASS || echo FAIL )
- fictional client walkthrough / demo flow present: $walkthrough_found

## Missing
$(if [[ ${#missing[@]} -gt 0 ]]; then printf -- '- %s\n' "${missing[@]}"; else echo '- none'; fi)

## Final Verdict
FINAL VERDICT: $( [[ "$pass" == true ]] && echo PASS || echo FAIL )
REPORT

if [[ "$pass" != true ]]; then
  echo "[$NOW_UTC] ACCEPTANCE_FAIL | scope=crypto_v1" >> logs/audit.log
  exit 1
fi

echo "[$NOW_UTC] ACCEPTANCE_PASS | scope=crypto_v1" >> logs/audit.log

echo ""
echo "=== [SECURITY] Supply-chain + Key Safety Gate ==="

mkdir -p deliver/proof/crypto
SEC_REPORT="deliver/proof/crypto/SECURITY_ACCEPTANCE.md"

# Check 1: denylist secret scan
echo "[SEC-1] scanning repo for forbidden secret patterns..."
set +e
FORBIDDEN_PATTERNS=(
  "BEGIN PRIVATE KEY"
  "seed phrase"
  "mnemonic"
  "AKIA"
  "sk_live"
  "-----BEGIN"
)
HIT=0
for pat in "${FORBIDDEN_PATTERNS[@]}"; do
  # scan tracked files only if git exists, else scan working tree excluding .venv
  # exclude deliver/crypto/security: policy docs intentionally name forbidden terms
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git grep -n "$pat" -- ':!deliver/crypto/security' >/dev/null 2>&1
    if [ $? -eq 0 ]; then
      echo "FAIL: found forbidden pattern in tracked files: $pat"
      HIT=1
    fi
  else
    grep -RIn --exclude-dir ".venv" --exclude-dir "__pycache__" --exclude-dir ".git" --exclude-dir "deliver/crypto/security" "$pat" . >/dev/null 2>&1
    if [ $? -eq 0 ]; then
      echo "FAIL: found forbidden pattern in repo: $pat"
      HIT=1
    fi
  fi
done
set -e
if [ "$HIT" -ne 0 ]; then
  echo "SECURITY_ACCEPTANCE: FAIL (secrets scan)" > "$SEC_REPORT"
  exit 1
fi
echo "OK: no forbidden secret patterns found"

# Check 2: security gate files exist
echo "[SEC-2] checking security gate file presence..."
test -f config/security_gate.yaml || { echo "FAIL: config/security_gate.yaml missing"; exit 1; }
test -f app/security_gate/policy.py || { echo "FAIL: app/security_gate/policy.py missing"; exit 1; }
test -f app/security_gate/gate.py || { echo "FAIL: app/security_gate/gate.py missing"; exit 1; }
test -f app/security_gate/cli.py || { echo "FAIL: app/security_gate/cli.py missing"; exit 1; }
test -f scripts/verify_security_gate.py || { echo "FAIL: scripts/verify_security_gate.py missing"; exit 1; }
echo "OK: security gate files present"

# Check 3: verify security gate behavior (non-interactive must deny)
echo "[SEC-3] running verify_security_gate.py..."
python3 scripts/verify_security_gate.py || { echo "FAIL: verify_security_gate.py failed"; exit 1; }
echo "OK: security gate verification passed"

# Write SECURITY_ACCEPTANCE proof
NOW_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
cat > "$SEC_REPORT" <<EOF
# Crypto V1 Security Acceptance
Generated: ${NOW_UTC}

## Checks
- SEC-1 Secrets denylist scan: PASS
- SEC-2 Security gate file presence: PASS
- SEC-3 Security gate behavior: PASS (non-interactive denies, logs written)

## Evidence
- config/security_gate.yaml
- scripts/verify_security_gate.py
- logs/security_gate.log
EOF

echo "SECURITY_ACCEPTANCE: PASS -> $SEC_REPORT"

echo ""
echo "=== [HARD CONSTRAINTS] Lockfile / Review / Runtime / Egress ==="

HC_REPORT="deliver/proof/crypto/HARDCONSTRAINTS_ACCEPTANCE.md"
DEP_REV="deliver/proof/DEPENDENCY_REVIEW.md"
mkdir -p deliver/proof/crypto data/dependency

CUR_REQ=$(shasum -a 256 requirements.txt | awk '{print $1}')
CUR_LOCK=$(shasum -a 256 requirements.lock.txt | awk '{print $1}')

echo "[HC-2] enterprise dependency audit signature (pre-verify)..."
if [[ ! -f "$DEP_REV" ]]; then
  echo "FAIL HC-2: deliver/proof/DEPENDENCY_REVIEW.md missing"
  exit 1
fi
REC_REQ=$(sed -n 's/^REQUIREMENTS_SHA256:[[:space:]]*//p' "$DEP_REV" | head -1 | tr -d '\r' | awk '{print $1}')
REC_LOCK=$(sed -n 's/^LOCK_SHA256:[[:space:]]*//p' "$DEP_REV" | head -1 | tr -d '\r' | awk '{print $1}')
if [[ -z "$REC_REQ" ]]; then
  echo "FAIL HC-2: REQUIREMENTS_SHA256 missing in DEPENDENCY_REVIEW.md"
  exit 1
fi
if [[ "$REC_REQ" != "$CUR_REQ" ]]; then
  echo "FAIL HC-2: requirements.txt changed without matching DEPENDENCY_REVIEW signature"
  exit 1
fi
if [[ -z "$REC_LOCK" ]]; then
  echo "FAIL HC-2: LOCK_SHA256 missing in DEPENDENCY_REVIEW.md"
  exit 1
fi
if [[ "$REC_LOCK" != "$CUR_LOCK" ]]; then
  echo "FAIL HC-2: requirements.lock.txt sha256 != LOCK_SHA256 in DEPENDENCY_REVIEW.md"
  exit 1
fi
echo "HC-2 signature match PASS (requirements + lock)"

echo "[HC] running scripts/verify_hardconstraints.py..."
set +e
VERIFY_OUT="$(python3 scripts/verify_hardconstraints.py 2>&1)"
VERIFY_CODE=$?
set -e
echo "$VERIFY_OUT"

NOW_HC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if [[ "$VERIFY_CODE" -ne 0 ]]; then
  cat > "$HC_REPORT" <<EOF
# Crypto V1 Hard Constraints Acceptance
Generated: ${NOW_HC}

## Results
${VERIFY_OUT}

## HC-2 evidence (pre-fail)
- requirements.txt sha256: ${CUR_REQ}
- DEPENDENCY_REVIEW REQUIREMENTS_SHA256: ${REC_REQ}
- requirements match: $([[ "$REC_REQ" == "$CUR_REQ" ]] && echo PASS || echo FAIL)
- lockfile sha256: ${CUR_LOCK}
- DEPENDENCY_REVIEW LOCK_SHA256: ${REC_LOCK}
- lock match: $([[ "$REC_LOCK" == "$CUR_LOCK" ]] && echo PASS || echo FAIL)

## Final
HARD CONSTRAINTS: FAIL (verify_hardconstraints.py exit ${VERIFY_CODE})
EOF
  echo "HARD CONSTRAINTS: FAIL -> $HC_REPORT"
  exit 1
fi

UTC_SIGN="$NOW_HC"
cat > "$DEP_REV" <<DOCREV
# Dependency Review (Crypto V1)

REQUIREMENTS_SHA256: ${CUR_REQ}
LOCK_SHA256: ${CUR_LOCK}
UTC_SIGNED: ${UTC_SIGN}
AUDITOR: local_accept

## What changed
- requirements.txt: signed via REQUIREMENTS_SHA256 above (single source of truth)
- requirements.lock.txt: signed via LOCK_SHA256 above

## Review checklist (V1)
- [ ] No new untrusted packages introduced
- [ ] No wildcard versions ("*", ">=0") in runtime deps
- [ ] Lockfile exists and enforces hashes
- [ ] External adapters remain OFF by default
- [ ] No secrets committed

## Commands
- sha256 requirements.txt:
  shasum -a 256 requirements.txt
- sha256 requirements.lock.txt:
  shasum -a 256 requirements.lock.txt
- diff requirements.txt:
  git diff -- requirements.txt || true
- regenerate lock (future, optional):
  (prefer pip-tools) pip-compile --generate-hashes -o requirements.lock.txt requirements.txt
DOCREV

cat > "$HC_REPORT" <<EOF
# Crypto V1 Hard Constraints Acceptance
Generated: ${NOW_HC}

## Results
${VERIFY_OUT}

## HC-2 dependency audit evidence
- requirements.txt sha256: ${CUR_REQ}
- DEPENDENCY_REVIEW recorded REQUIREMENTS_SHA256: ${REC_REQ}
- match: PASS
- lockfile sha256: ${CUR_LOCK}
- DEPENDENCY_REVIEW recorded LOCK_SHA256: ${REC_LOCK}
- lock match: PASS

## Checks
- HC-1 Lockfile (requirements.lock.txt + per-line --hash=sha256:): PASS
- HC-2 DEPENDENCY_REVIEW signed signatures (requirements + lock): PASS
- HC-3 Runtime isolation (no keys in main process; external_runtime guard): PASS
- HC-4 Egress audit (config + resolve + logs/egress_audit.log): PASS

## Evidence
- requirements.lock.txt
- deliver/proof/DEPENDENCY_REVIEW.md
- app/security_gate/external_runtime.py
- config/egress_policy.yaml
- logs/egress_audit.log
EOF

echo "HARD CONSTRAINTS: PASS -> $HC_REPORT"
