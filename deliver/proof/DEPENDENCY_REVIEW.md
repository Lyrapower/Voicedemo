# Dependency Review (Crypto V1)

REQUIREMENTS_SHA256: 55b29bf871cf8e8c46eaf574efdcd6b2133b3f3aabf089be83ee6708a16c767a
LOCK_SHA256: cffe92e579c0e2261c979b13bd56fec03eba8bea0fb2d54a625ccd5e78720ea9
UTC_SIGNED: 2026-04-24T13:00:44Z
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
