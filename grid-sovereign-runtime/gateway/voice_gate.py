"""WS /voice keyholder gate — rate limit + audit (no key material)."""
from __future__ import annotations

import json
import time
from pathlib import Path

_FAILS: dict[str, dict] = {}
_LOCK_UNTIL: dict[str, float] = {}
MAX_FAILS = 3
LOCK_SECONDS = 60
FAIL_STALE_SECONDS = 120


def _peer(host: str | None) -> str:
    return (host or "unknown").split("%")[0]


def is_locked(host: str | None) -> tuple[bool, float | None]:
    peer = _peer(host)
    until = _LOCK_UNTIL.get(peer)
    now = time.time()
    if until and now < until:
        return True, until
    if until:
        _LOCK_UNTIL.pop(peer, None)
        _FAILS.pop(peer, None)
    return False, None


def record_success(host: str | None) -> None:
    peer = _peer(host)
    _FAILS.pop(peer, None)
    _LOCK_UNTIL.pop(peer, None)


def record_failure(host: str | None, *, code: str, detail: str) -> dict:
    peer = _peer(host)
    now = time.time()
    st = _FAILS.get(peer) or {"count": 0, "last": 0.0}
    if now - st["last"] > FAIL_STALE_SECONDS:
        st["count"] = 0
    st["count"] += 1
    st["last"] = now
    _FAILS[peer] = st
    locked_until = None
    if st["count"] >= MAX_FAILS:
        locked_until = now + LOCK_SECONDS
        _LOCK_UNTIL[peer] = locked_until
    return {
        "peer": peer,
        "fail_count": st["count"],
        "locked": locked_until is not None,
        "locked_until": locked_until,
        "code": code,
        "detail": detail,
    }


def audit_failure(log_path: Path, row: dict) -> None:
    """Audit voice handshake failure — never log key/response/hash."""
    safe = {
        "ts": time.time(),
        "event": "voice.handshake_fail",
        "peer": row.get("peer"),
        "code": row.get("code"),
        "detail": row.get("detail"),
        "fail_count": row.get("fail_count"),
        "locked": row.get("locked"),
        "locked_until": row.get("locked_until"),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe, ensure_ascii=False) + "\n")
