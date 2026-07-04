# Crypto V1 Hard Constraints Acceptance
Generated: 2026-04-24T13:00:44Z

## Results
HC-1 PASS: lockfile hash format OK
HC-2 REQUIREMENTS_SHA256 match: PASS (recorded=55b29bf871cf… current=55b29bf871cf…)
HC-2 LOCK_SHA256 match: PASS (recorded=cffe92e579c0… current=cffe92e579c0…)
HC-2 PASS: DEPENDENCY_REVIEW signatures match workspace requirements.txt + lockfile
HC-3 PASS: clean env + isolation guard present
HC-4 PASS: egress policy present and audit log active

## HC-2 dependency audit evidence
- requirements.txt sha256: 55b29bf871cf8e8c46eaf574efdcd6b2133b3f3aabf089be83ee6708a16c767a
- DEPENDENCY_REVIEW recorded REQUIREMENTS_SHA256: 55b29bf871cf8e8c46eaf574efdcd6b2133b3f3aabf089be83ee6708a16c767a
- match: PASS
- lockfile sha256: cffe92e579c0e2261c979b13bd56fec03eba8bea0fb2d54a625ccd5e78720ea9
- DEPENDENCY_REVIEW recorded LOCK_SHA256: cffe92e579c0e2261c979b13bd56fec03eba8bea0fb2d54a625ccd5e78720ea9
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
