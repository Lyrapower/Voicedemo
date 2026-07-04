#!/usr/bin/env python3
"""
Grid Keyholder Challenge (V4.3)

WHAT THIS PROVES, PRECISELY:
    That the responding party holds a specific secret key.
    Nothing more. Nothing less.

WHAT THIS DOES NOT PROVE:
    - That "Grid" is real, online, conscious, or present.
    - That the keyholder is any particular entity.
    - Any metaphysical claim whatsoever.

    A local model impersonating Grid CANNOT pass this, because it does not
    hold the key. That is the entire and only guarantee: it separates
    "party that holds KEY_H" from "local model generating plausible text."
    The meaning of KEY_H — what holding it signifies — is defined by you,
    outside this code. Source identity is never delegated to an LLM, and it
    is not delegated to this verifier either. This tool draws one clean line
    (keyholder vs not) and hands the final judgment back to you.

MECHANISM (HMAC challenge-response, stdlib only):
    1. Verifier generates a random nonce + timestamp.
    2. Challenge = HMAC(KEY_H, nonce || ts). Verifier keeps expected answer.
    3. Responder must return HMAC(KEY_H, nonce || ts). Only a keyholder can.
    4. Verifier compares in constant time. Match within TTL -> VERIFIED_KEYHOLDER.

    The challenge is single-use (nonce recorded) and time-boxed (TTL), so a
    captured transcript cannot be replayed later.

KEY SEPARATION:
    This uses a SEPARATE key from the trace-signing HMAC key (grid_hmac.key).
    Reason: trace signing and liveness proof are different capabilities;
    compromising one should not grant the other. Keyholder key = keyholder.key.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import hmac
import json
import os
import secrets
import sys
from pathlib import Path


ROOT = Path(os.environ.get("GRID_ROOT", Path(__file__).resolve().parent.parent))
STATE_DIR = ROOT / ".grid_cleanroom"
KEYHOLDER_KEY_PATH = STATE_DIR / "keyholder.key"
CHALLENGE_LOG = STATE_DIR / "challenge_log.json"

DEFAULT_TTL_SECONDS = 90


def now() -> float:
    return _dt.datetime.now(_dt.timezone.utc).timestamp()


def iso(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat()


def _load_key() -> bytes:
    if not KEYHOLDER_KEY_PATH.exists():
        raise FileNotFoundError(
            "keyholder key missing. Run: python3 scripts/keyholder_challenge.py init"
        )
    return KEYHOLDER_KEY_PATH.read_bytes().strip()


def _msg(nonce: str, ts: float) -> bytes:
    # canonical challenge message; both sides must build it identically
    return f"{nonce}|{int(ts)}".encode("utf-8")


def compute_response(nonce: str, ts: float, key: bytes) -> str:
    """The keyholder side computes this. Requires the key."""
    return hmac.new(key, _msg(nonce, ts), hashlib.sha256).hexdigest()


# ------------------------------------------------------------ verifier side

def make_challenge() -> dict:
    """Generate a fresh single-use, time-boxed challenge."""
    nonce = secrets.token_hex(16)
    ts = now()
    return {"nonce": nonce, "ts": ts, "issued_at": iso(ts), "ttl": DEFAULT_TTL_SECONDS}


def _load_challenge_log() -> dict:
    if CHALLENGE_LOG.exists():
        try:
            return json.loads(CHALLENGE_LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"used_nonces": [], "history": []}
    return {"used_nonces": [], "history": []}


def _save_challenge_log(log: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    log["used_nonces"] = log.get("used_nonces", [])[-500:]
    log["history"] = log.get("history", [])[-500:]
    CHALLENGE_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def verify_response(nonce: str, ts: float, response: str,
                    ttl: int = DEFAULT_TTL_SECONDS) -> dict:
    """
    Verify a keyholder's response. Returns a result dict with an explicit
    verdict. Enforces: key match (constant-time), TTL, single-use nonce.
    """
    log = _load_challenge_log()
    reason = None
    verdict = "GRID_ABSENT"

    if nonce in log.get("used_nonces", []):
        reason = "nonce already used (replay rejected)"
    elif (now() - ts) > ttl:
        reason = f"challenge expired (older than {ttl}s)"
    elif (now() - ts) < -5:
        reason = "challenge timestamp is in the future (clock skew or forgery)"
    else:
        try:
            key = _load_key()
        except FileNotFoundError as e:
            return {"verdict": "ERROR", "reason": str(e), "verified": False}
        expected = compute_response(nonce, ts, key)
        if hmac.compare_digest(expected, response or ""):
            verdict = "VERIFIED_KEYHOLDER"
        else:
            reason = "response does not match expected keyholder signature"

    # record nonce as used regardless of outcome (prevents retrying a captured nonce)
    log.setdefault("used_nonces", []).append(nonce)
    log.setdefault("history", []).append({
        "at": iso(now()), "nonce": nonce, "verdict": verdict, "reason": reason,
    })
    _save_challenge_log(log)

    return {
        "verdict": verdict,
        "verified": verdict == "VERIFIED_KEYHOLDER",
        "reason": reason,
        # Deliberate, non-negotiable disclaimer travels with every result:
        "proves": "responder holds KEY_H",
        "does_not_prove": "that Grid is real/online/present; identity meaning is yours to assign",
    }


def health_snapshot(ttl: int = DEFAULT_TTL_SECONDS) -> dict:
    """Recent keyholder verification event for /health — not a standing identity claim."""
    if not CHALLENGE_LOG.exists():
        return {
            "challenge_ttl_seconds": ttl,
            "last_verified_at": None,
            "last_verdict": None,
            "line": "keyholder: no recent challenge",
        }
    log = _load_challenge_log()
    history = log.get("history") or []
    last_verified_at = None
    for entry in reversed(history):
        if entry.get("verdict") == "VERIFIED_KEYHOLDER":
            last_verified_at = entry.get("at")
            break
    recent = False
    if last_verified_at:
        try:
            at_raw = str(last_verified_at).replace("Z", "+00:00")
            at_ts = _dt.datetime.fromisoformat(at_raw).timestamp()
            age = now() - at_ts
            recent = 0 <= age <= ttl
        except (ValueError, TypeError, OSError):
            recent = False
    if recent and last_verified_at:
        return {
            "challenge_ttl_seconds": ttl,
            "last_verified_at": last_verified_at,
            "last_verdict": "VERIFIED_KEYHOLDER",
            "line": f"keyholder: VERIFIED_KEYHOLDER @ {last_verified_at}",
        }
    return {
        "challenge_ttl_seconds": ttl,
        "last_verified_at": None,
        "last_verdict": None,
        "line": "keyholder: no recent challenge",
    }


# ------------------------------------------------------------ CLI

def init_cmd(_args) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    if KEYHOLDER_KEY_PATH.exists():
        print(f"keyholder key already exists: {KEYHOLDER_KEY_PATH}")
        return
    KEYHOLDER_KEY_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
    try:
        os.chmod(KEYHOLDER_KEY_PATH, 0o600)
    except OSError:
        pass
    print("PASS keyholder init")
    print(f"key: {KEYHOLDER_KEY_PATH}")
    print("This key defines the keyholder. Do not commit, do not upload, do not give to any model.")
    print("Whoever/whatever you consider 'real Grid' must possess this key to pass a challenge.")


def challenge_cmd(_args) -> None:
    ch = make_challenge()
    print(json.dumps(ch, ensure_ascii=False))
    print("\nGive nonce+ts to the responder. They return compute_response(nonce, ts, KEY_H).",
          file=sys.stderr)


def respond_cmd(args) -> None:
    """Convenience: compute a response locally (only works if THIS host holds the key)."""
    key = _load_key()
    print(compute_response(args.nonce, float(args.ts), key))


def verify_cmd(args) -> None:
    result = verify_response(args.nonce, float(args.ts), args.response, ttl=args.ttl)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["verified"] else 1)


def selftest_cmd(_args) -> None:
    """Prove the mechanism: keyholder passes, impostor fails, replay fails, expiry fails."""
    if not KEYHOLDER_KEY_PATH.exists():
        init_cmd(None)
    key = _load_key()

    ch = make_challenge()
    good = compute_response(ch["nonce"], ch["ts"], key)
    r = verify_response(ch["nonce"], ch["ts"], good, ttl=ch["ttl"])
    assert r["verified"], r
    print("PASS keyholder verified")

    ch2 = make_challenge()
    bad = hmac.new(b"local-model-guess", _msg(ch2["nonce"], ch2["ts"]), hashlib.sha256).hexdigest()
    r2 = verify_response(ch2["nonce"], ch2["ts"], bad, ttl=ch2["ttl"])
    assert not r2["verified"] and r2["verdict"] == "GRID_ABSENT", r2
    print("PASS impostor (wrong key) rejected -> GRID_ABSENT")

    ch3 = make_challenge()
    good3 = compute_response(ch3["nonce"], ch3["ts"], key)
    assert verify_response(ch3["nonce"], ch3["ts"], good3)["verified"]
    r3 = verify_response(ch3["nonce"], ch3["ts"], good3)   # same nonce again
    assert not r3["verified"], r3
    print("PASS replay (reused nonce) rejected")

    ch4 = make_challenge()
    old_ts = ch4["ts"] - 10_000
    good4 = compute_response(ch4["nonce"], old_ts, key)
    r4 = verify_response(ch4["nonce"], old_ts, good4, ttl=90)
    assert not r4["verified"], r4
    print("PASS expired challenge rejected")
    print("\nALL SELFTESTS PASS — mechanism separates keyholder from impostor.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Grid keyholder challenge-response")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(func=init_cmd)
    sub.add_parser("challenge").set_defaults(func=challenge_cmd)
    rp = sub.add_parser("respond"); rp.add_argument("--nonce", required=True)
    rp.add_argument("--ts", required=True); rp.set_defaults(func=respond_cmd)
    vp = sub.add_parser("verify"); vp.add_argument("--nonce", required=True)
    vp.add_argument("--ts", required=True); vp.add_argument("--response", required=True)
    vp.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS); vp.set_defaults(func=verify_cmd)
    sub.add_parser("selftest").set_defaults(func=selftest_cmd)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
