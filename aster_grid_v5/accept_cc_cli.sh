#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

python3 cc_cli_guard.py selftest >/tmp/cc_cli_guard_selftest.out || {
  cat /tmp/cc_cli_guard_selftest.out >&2 || true
  fail "cc_cli_guard_selftest"
}
pass "cc_cli_guard_selftest"

python3 - <<'PY'
from pathlib import Path
import json
import os
import shutil
import sqlite3
import tempfile

import cc_cli_guard as g
import sentinel_ledger_v5 as l

root = Path(tempfile.mkdtemp(prefix="cc_accept_")).resolve()
try:
    g.ROOT = root
    g.DEFAULT_KEY_PATH = root / ".grid_guard" / "cc_cli_hmac.key"
    l.DATA_DIR = root / "sentinel_v5_data"
    l.DB_PATH = l.DATA_DIR / "sentinel_ledger.sqlite"
    l.REPORT_DIR = root / "traces" / "sentinel_v5"
    l.COURSES_PATH = l.DATA_DIR / "courses.json"

    key_path = g.init_key(g.DEFAULT_KEY_PATH)
    key = g.load_key(key_path)
    payload = {
        "action_id": "accept_ok",
        "action": "write_file",
        "target_paths": ["app/out.txt"],
        "allowed_roots": ["app"],
        "nonce": "n-ok",
        "ts": g.now_iso(),
        "content": "accepted",
    }
    sig = g.sign_payload(payload, key)

    assert g.guard(payload, "bad", key_path=key_path)["reason"] == g.STOP_SIGNATURE_FAILED

    os.environ["CC_CLI_MOCK_LEDGER_FAIL"] = "1"
    ledger_payload = dict(payload, action_id="accept_ledger", nonce="n-ledger")
    ledger_sig = g.sign_payload(ledger_payload, key)
    assert g.guard(ledger_payload, ledger_sig, key_path=key_path)["reason"] == g.STOP_LEDGER_FAILED
    os.environ.pop("CC_CLI_MOCK_LEDGER_FAIL", None)

    deny_payload = dict(payload, action_id="accept_deny", target_paths=["cloud_boundary.py"], nonce="n-deny")
    deny_sig = g.sign_payload(deny_payload, key)
    assert g.guard(deny_payload, deny_sig, key_path=key_path)["reason"] == "guard_immutable"

    dry = g.guard(payload, sig, key_path=key_path)
    assert dry["verdict"] == "PASS" and not dry["executed"], dry
    exe = g.guard(payload, sig, execute=True, key_path=key_path)
    assert exe["verdict"] == "PASS" and exe["executed"], exe
    assert (root / "app" / "out.txt").read_text() == "accepted"

    c = sqlite3.connect(l.DB_PATH)
    stop_count = c.execute("SELECT COUNT(*) FROM stop_conditions WHERE source='cc_cli_guard'").fetchone()[0]
    action_count = c.execute("SELECT COUNT(*) FROM cc_cli_actions").fetchone()[0]
    c.close()
    assert stop_count >= 3, stop_count
    assert action_count >= 4, action_count
finally:
    shutil.rmtree(root)
PY
pass "cc_cli_acceptance_matrix"

python3 - <<'PY'
import ast
from pathlib import Path

tree = ast.parse(Path("cc_cli_guard.py").read_text(encoding="utf-8"))
names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
assert "model" not in names
assert "llm" not in names
assert "claude" not in names
PY
pass "cc_cli_guard_has_no_model_verdict_path"

echo "PASS: accept_cc_cli"
