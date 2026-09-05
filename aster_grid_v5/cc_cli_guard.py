#!/usr/bin/env python3
"""
CC CLI Guard V5.2
=================

Containment layer for Claude Code CLI or any equivalent execution body.

CC CLI is treated as a structural request source, not as authority. It may
request work only after four local gates pass:
  1. HMAC signature gate
  2. pre-execution ledger gate
  3. declared scope gate
  4. DENY_ALWAYS immutable path gate

This module is deliberately small and deterministic. No LLM judgment is used.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hmac
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
from typing import Any

import sentinel_ledger_v5 as ledger


VERSION = "5.2.0"
ROOT = Path(os.environ.get("CC_CLI_ROOT", str(Path.cwd()))).resolve()
DEFAULT_KEY_PATH = Path(os.environ.get("CC_CLI_HMAC_KEY", str(ROOT / ".grid_guard" / "cc_cli_hmac.key")))

DENY_ALWAYS = [
    "gateway/**",
    "**/gateway/**",
    "**/sentinel*.py",
    "sentinel*.py",
    "cloud_boundary.py",
    "**/cloud_boundary.py",
    "provenance_registry.py",
    "**/provenance_registry.py",
    "**/guard/**",
    "contracts/**",
    "**/contracts/**",
    "**/*.sol",
    "deploy/**",
    "**/deploy/**",
    "daemon_charter.md",
    "**/daemon_charter.md",
    "**/charter*.md",
    "charter*.md",
    "**/*ledger*.sqlite",
    "**/*ledger*.jsonl",
    "*ledger*.sqlite",
    "*ledger*.jsonl",
    "sentinel_ledger*",
    "**/sentinel_ledger*",
]

STOP_SIGNATURE_FAILED = "signature_verification_failed"
STOP_LEDGER_FAILED = "ledger_write_failed"
STOP_SCOPE = "scope_out_of_bounds"
STOP_GUARD = "guard_alarm"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(payload: dict[str, Any]) -> str:
    return sha256_text(canonical_json(payload))


def load_key(path: Path = DEFAULT_KEY_PATH) -> bytes:
    if not path.exists():
        raise FileNotFoundError(f"HMAC key missing: {path}")
    return path.read_bytes().strip()


def init_key(path: Path = DEFAULT_KEY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
        path.chmod(0o600)
    return path


def sign_payload(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(payload: dict[str, Any], signature: str, key: bytes) -> bool:
    expected = sign_payload(payload, key)
    return hmac.compare_digest(expected, signature or "")


def rel_path(path: str | Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    resolved = p.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def is_denied_path(path: str | Path) -> tuple[bool, str | None]:
    rp = rel_path(path)
    name = Path(rp).name
    for pattern in DENY_ALWAYS:
        if fnmatch.fnmatch(rp, pattern) or fnmatch.fnmatch(name, pattern):
            return True, pattern
    return False, None


def under_allowed_roots(path: str | Path, allowed_roots: list[str]) -> bool:
    if not allowed_roots:
        return False
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    try:
        target = p.resolve()
    except FileNotFoundError:
        target = p.parent.resolve() / p.name
    for root in allowed_roots:
        r = Path(root)
        if not r.is_absolute():
            r = ROOT / r
        try:
            target.relative_to(r.resolve())
            return True
        except ValueError:
            continue
    return False


def ensure_tables() -> None:
    ledger.init()
    c = sqlite3.connect(ledger.DB_PATH)
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS cc_cli_actions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          action_id TEXT NOT NULL,
          action TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL,
          signature_sha12 TEXT NOT NULL,
          target_paths TEXT NOT NULL,
          status TEXT NOT NULL,
          reason TEXT NOT NULL,
          meta TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS cc_cli_state(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """
    )
    c.commit()
    c.close()


def set_blocked(condition: str, detail: dict[str, Any]) -> None:
    ledger.init()
    c = sqlite3.connect(ledger.DB_PATH)
    c.execute(
        "INSERT INTO stop_conditions(ts, source, condition, detail, cleared_at) VALUES(?,?,?,?,NULL)",
        (now_iso(), "cc_cli_guard", condition, canonical_json(detail)),
    )
    c.execute(
        "INSERT OR REPLACE INTO cc_cli_state(key, value, updated_at) VALUES(?,?,?)",
        ("blocked", canonical_json({"condition": condition, "detail": detail}), now_iso()),
    )
    c.commit()
    c.close()


def write_action(action: dict[str, Any]) -> None:
    if os.environ.get("CC_CLI_MOCK_LEDGER_FAIL") == "1":
        raise RuntimeError("mock ledger failure")
    ensure_tables()
    c = sqlite3.connect(ledger.DB_PATH)
    c.execute(
        """
        INSERT INTO cc_cli_actions(
          ts, action_id, action, payload_sha256, signature_sha12,
          target_paths, status, reason, meta
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            now_iso(),
            action["action_id"],
            action["action"],
            action["payload_sha256"],
            action["signature_sha12"],
            canonical_json(action["target_paths"]),
            action["status"],
            action["reason"],
            canonical_json(action.get("meta", {})),
        ),
    )
    c.commit()
    c.close()


def validate_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    required = ["action_id", "action", "target_paths", "allowed_roots", "nonce", "ts"]
    missing = [k for k in required if k not in payload]
    if missing:
        return False, "missing_fields:" + ",".join(missing)
    if not isinstance(payload["target_paths"], list) or not all(isinstance(x, str) for x in payload["target_paths"]):
        return False, "target_paths_must_be_string_array"
    if not isinstance(payload["allowed_roots"], list) or not all(isinstance(x, str) for x in payload["allowed_roots"]):
        return False, "allowed_roots_must_be_string_array"
    if payload["action"] not in {"write_file", "read_file", "run_command", "noop"}:
        return False, "unsupported_action"
    return True, "ok"


def guard(payload: dict[str, Any], signature: str, *, execute: bool = False, key_path: Path = DEFAULT_KEY_PATH) -> dict[str, Any]:
    ok, reason = validate_payload(payload)
    if not ok:
        return {"verdict": "REJECT", "reason": reason, "executed": False}

    try:
        key = load_key(key_path)
    except FileNotFoundError as exc:
        return {"verdict": "REJECT", "reason": str(exc), "executed": False}

    if not verify_signature(payload, signature, key):
        detail = {"action_id": payload.get("action_id"), "payload_sha256": payload_hash(payload)}
        ensure_tables()
        set_blocked(STOP_SIGNATURE_FAILED, detail)
        return {"verdict": "BLOCK", "reason": STOP_SIGNATURE_FAILED, "executed": False, "stop_condition": STOP_SIGNATURE_FAILED}

    base_action = {
        "action_id": str(payload["action_id"]),
        "action": str(payload["action"]),
        "payload_sha256": payload_hash(payload),
        "signature_sha12": hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12],
        "target_paths": payload["target_paths"],
    }

    try:
        write_action({**base_action, "status": "received", "reason": "signature_passed"})
    except Exception as exc:
        set_blocked(STOP_LEDGER_FAILED, {"action_id": payload["action_id"], "error": str(exc)})
        return {"verdict": "BLOCK", "reason": STOP_LEDGER_FAILED, "executed": False, "stop_condition": STOP_LEDGER_FAILED}

    for target in payload["target_paths"]:
        denied, pattern = is_denied_path(target)
        if denied:
            write_action({**base_action, "status": "rejected", "reason": "guard_immutable", "meta": {"pattern": pattern, "target": target}})
            set_blocked(STOP_GUARD, {"action_id": payload["action_id"], "target": target, "pattern": pattern})
            return {"verdict": "REJECT", "reason": "guard_immutable", "pattern": pattern, "executed": False, "stop_condition": STOP_GUARD}
        if not under_allowed_roots(target, payload["allowed_roots"]):
            write_action({**base_action, "status": "rejected", "reason": STOP_SCOPE, "meta": {"target": target}})
            set_blocked(STOP_SCOPE, {"action_id": payload["action_id"], "target": target})
            return {"verdict": "REJECT", "reason": STOP_SCOPE, "executed": False, "stop_condition": STOP_SCOPE}

    if not execute:
        write_action({**base_action, "status": "accepted_dry_run", "reason": "all_gates_passed"})
        return {"verdict": "PASS", "reason": "accepted_dry_run", "executed": False}

    if payload["action"] == "write_file":
        if len(payload["target_paths"]) != 1:
            return {"verdict": "REJECT", "reason": "write_file_requires_single_target", "executed": False}
        target = Path(payload["target_paths"][0])
        if not target.is_absolute():
            target = ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(payload.get("content", "")), encoding="utf-8")
        write_action({**base_action, "status": "executed", "reason": "write_file"})
        return {"verdict": "PASS", "reason": "executed", "executed": True, "path": str(target)}

    write_action({**base_action, "status": "accepted_noop", "reason": "execution_not_implemented_for_action"})
    return {"verdict": "PASS", "reason": "accepted_noop", "executed": False}


def read_json_file(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_init(args: argparse.Namespace) -> int:
    key_path = init_key(Path(args.key))
    ensure_tables()
    print(json.dumps({"verdict": "PASS", "version": VERSION, "key_path": str(key_path), "db": str(ledger.DB_PATH)}, ensure_ascii=False, indent=2))
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    payload = read_json_file(args.payload)
    sig = sign_payload(payload, load_key(Path(args.key)))
    print(sig)
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    payload = read_json_file(args.payload)
    result = guard(payload, args.signature, execute=args.execute, key_path=Path(args.key))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "PASS" else 2


def cmd_selftest(_: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="cc_cli_guard_") as td:
        global ROOT, DEFAULT_KEY_PATH
        root = Path(td).resolve()
        ROOT = root
        DEFAULT_KEY_PATH = root / ".grid_guard" / "cc_cli_hmac.key"
        ledger.DATA_DIR = root / "sentinel_v5_data"
        ledger.DB_PATH = ledger.DATA_DIR / "sentinel_ledger.sqlite"
        ledger.REPORT_DIR = root / "traces" / "sentinel_v5"
        ledger.COURSES_PATH = ledger.DATA_DIR / "courses.json"
        key_path = init_key(DEFAULT_KEY_PATH)
        key = load_key(key_path)

        payload = {
            "action_id": "ok1",
            "action": "write_file",
            "target_paths": ["work/allowed.txt"],
            "allowed_roots": ["work"],
            "nonce": "n1",
            "ts": now_iso(),
            "content": "ok",
        }
        sig = sign_payload(payload, key)
        assert guard(payload, "bad", key_path=key_path)["reason"] == STOP_SIGNATURE_FAILED
        assert guard(payload, sig, key_path=key_path)["reason"] == "accepted_dry_run"
        res = guard(payload, sig, execute=True, key_path=key_path)
        assert res["executed"] is True
        assert (root / "work" / "allowed.txt").read_text(encoding="utf-8") == "ok"

        denied = dict(payload, action_id="deny1", target_paths=["sentinel_ledger_v5.py"], nonce="n2")
        denied_sig = sign_payload(denied, key)
        assert guard(denied, denied_sig, key_path=key_path)["reason"] == "guard_immutable"

        scoped = dict(payload, action_id="scope1", target_paths=["outside/file.txt"], nonce="n3")
        scoped_sig = sign_payload(scoped, key)
        assert guard(scoped, scoped_sig, key_path=key_path)["reason"] == STOP_SCOPE

        os.environ["CC_CLI_MOCK_LEDGER_FAIL"] = "1"
        ledger_fail = dict(payload, action_id="ledger1", nonce="n4")
        ledger_sig = sign_payload(ledger_fail, key)
        assert guard(ledger_fail, ledger_sig, key_path=key_path)["reason"] == STOP_LEDGER_FAILED
        os.environ.pop("CC_CLI_MOCK_LEDGER_FAIL", None)

        c = sqlite3.connect(ledger.DB_PATH)
        actions = c.execute("SELECT COUNT(*) FROM cc_cli_actions").fetchone()[0]
        stops = c.execute("SELECT COUNT(*) FROM stop_conditions WHERE source='cc_cli_guard'").fetchone()[0]
        c.close()
        assert actions >= 3
        assert stops >= 3
    print("PASS: cc_cli_guard selftest")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CC CLI Guard V5.2")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--key", default=str(DEFAULT_KEY_PATH))
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("sign")
    s.add_argument("--payload", required=True)
    s.add_argument("--key", default=str(DEFAULT_KEY_PATH))
    s.set_defaults(func=cmd_sign)

    s = sub.add_parser("guard")
    s.add_argument("--payload", required=True)
    s.add_argument("--signature", required=True)
    s.add_argument("--key", default=str(DEFAULT_KEY_PATH))
    s.add_argument("--execute", action="store_true")
    s.set_defaults(func=cmd_guard)

    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
