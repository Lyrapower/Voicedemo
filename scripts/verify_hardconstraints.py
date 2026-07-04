from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock.txt"
REQ = ROOT / "requirements.txt"
REVIEW = ROOT / "deliver" / "proof" / "DEPENDENCY_REVIEW.md"
EGRESS_CFG = ROOT / "config" / "egress_policy.yaml"
EGRESS_LOG = ROOT / "logs" / "egress_audit.log"
EXT_RT = ROOT / "app" / "security_gate" / "external_runtime.py"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hc1_lockfile() -> tuple[bool, str]:
    if not LOCK.exists():
        return False, "HC-1 FAIL: requirements.lock.txt missing"
    text = LOCK.read_text(encoding="utf-8", errors="replace")
    if "HASH_LOCK_REQUIRED" not in text:
        return False, "HC-1 FAIL: HASH_LOCK_REQUIRED header missing"
    if "--hash=sha256:" not in text:
        return False, "HC-1 FAIL: no --hash=sha256: in lockfile"
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "--hash=sha256:" not in line:
            return False, f"HC-1 FAIL: line {i} missing --hash=sha256: {line[:80]!r}"
    return True, "HC-1 PASS: lockfile hash format OK"


def _parse_signed_line(text: str, prefix: str) -> Optional[str]:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(prefix):
            val = s[len(prefix) :].strip()
            return val.split()[0] if val else None
    return None


def hc2_dependency_review() -> tuple[bool, str]:
    if not REVIEW.exists():
        return False, "HC-2 FAIL: deliver/proof/DEPENDENCY_REVIEW.md missing"
    body = REVIEW.read_text(encoding="utf-8", errors="replace")
    rec_req = _parse_signed_line(body, "REQUIREMENTS_SHA256:")
    rec_lock = _parse_signed_line(body, "LOCK_SHA256:")
    if not rec_req:
        return False, "HC-2 FAIL: REQUIREMENTS_SHA256 missing in DEPENDENCY_REVIEW.md"
    if not rec_lock:
        return False, "HC-2 FAIL: LOCK_SHA256 missing in DEPENDENCY_REVIEW.md"
    cur_req = _sha256_file(REQ)
    cur_lock = _sha256_file(LOCK)
    ok_req = rec_req == cur_req
    ok_lock = rec_lock == cur_lock
    print(f"HC-2 REQUIREMENTS_SHA256 match: {'PASS' if ok_req else 'FAIL'} (recorded={rec_req[:12]}… current={cur_req[:12]}…)")
    print(f"HC-2 LOCK_SHA256 match: {'PASS' if ok_lock else 'FAIL'} (recorded={rec_lock[:12]}… current={cur_lock[:12]}…)")
    if not ok_req:
        return False, "HC-2 FAIL: requirements.txt sha256 != REQUIREMENTS_SHA256 in DEPENDENCY_REVIEW.md"
    if not ok_lock:
        return False, "HC-2 FAIL: requirements.lock.txt sha256 != LOCK_SHA256 in DEPENDENCY_REVIEW.md"
    return True, "HC-2 PASS: DEPENDENCY_REVIEW signatures match workspace requirements.txt + lockfile"


def hc3_runtime_isolation() -> tuple[bool, str]:
    if os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
        return False, "HC-3 FAIL: API keys must not be set in main process during acceptance"
    if not EXT_RT.exists():
        return False, "HC-3 FAIL: app/security_gate/external_runtime.py missing"
    body = EXT_RT.read_text(encoding="utf-8", errors="replace")
    if "SECURITY_FAIL" not in body or "keys present in main process env" not in body:
        return False, "HC-3 FAIL: external_runtime.py missing SECURITY_FAIL / keys check"
    return True, "HC-3 PASS: clean env + isolation guard present"


def hc4_egress_audit() -> tuple[bool, str]:
    if not EGRESS_CFG.exists():
        return False, "HC-4 FAIL: config/egress_policy.yaml missing"
    sys.path.insert(0, str(ROOT))
    try:
        from app.security_gate.egress_audit import resolve

        try:
            resolve("api.openai.com")
        except OSError:
            # DNS may fail in some environments; log_attempt runs before gethostbyname
            pass
    finally:
        if sys.path and sys.path[0] == str(ROOT):
            sys.path.pop(0)
    if not EGRESS_LOG.exists():
        return False, "HC-4 FAIL: logs/egress_audit.log not created"
    log_text = EGRESS_LOG.read_text(encoding="utf-8")
    if "api.openai.com" not in log_text:
        return False, "HC-4 FAIL: no egress log entry for api.openai.com"
    return True, "HC-4 PASS: egress policy present and audit log active"


def main() -> int:
    os.chdir(ROOT)
    results = []
    for fn in (hc1_lockfile, hc2_dependency_review, hc3_runtime_isolation, hc4_egress_audit):
        ok, msg = fn()
        results.append((ok, msg))
        print(msg)
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
