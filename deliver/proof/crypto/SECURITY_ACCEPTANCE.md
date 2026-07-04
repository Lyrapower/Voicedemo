# Crypto V1 Security Acceptance
Generated: 2026-04-24T13:00:43Z

## Checks
- SEC-1 Secrets denylist scan: PASS
- SEC-2 Security gate file presence: PASS
- SEC-3 Security gate behavior: PASS (non-interactive denies, logs written)

## Evidence
- config/security_gate.yaml
- scripts/verify_security_gate.py
- logs/security_gate.log
