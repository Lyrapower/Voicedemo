#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

CHECK_LAUNCHD=0
if [[ "${1:-}" == "--check-launchd" ]]; then
  CHECK_LAUNCHD=1
fi

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

./referee_selftest.sh >/tmp/aster_v5_referee_selftest.out || {
  cat /tmp/aster_v5_referee_selftest.out >&2 || true
  fail "referee_selftest"
}
pass "referee_selftest"

./accept_cc_cli.sh >/tmp/aster_v5_cc_cli_accept.out || {
  cat /tmp/aster_v5_cc_cli_accept.out >&2 || true
  fail "accept_cc_cli"
}
pass "accept_cc_cli"

python3 - <<'PY'
import cloud_boundary
assert not cloud_boundary.is_cloud_safe({"x":"私钥保管好"})
assert cloud_boundary.is_cloud_safe({"x":"auth token budget"})
assert not cloud_boundary.is_cloud_safe({"x":"token = sk-abc12345"})
assert not cloud_boundary.is_cloud_safe({"user_text":"clean","qwen_draft":"token = sk-abc12345"})
PY
pass "cloud_boundary_probes"

python3 - <<'PY'
import provenance_registry as p
text = "DeepSeek historical screen says AAPL calls look strong gamma favorable into close"
p.register_text(text, "acceptance_probe")
r = p.check_provenance("AAPL calls look strong gamma favorable into close")
assert not r["clean"], r
assert r["overlap_ratio"] > 0.15, r
PY
pass "provenance_laundering_probe"

python3 - <<'PY'
import json
import aster_fable_bridge_v5 as b
record = {
    "id":"acceptance_manual_review",
    "created_at":b.now_iso(),
    "access_level":"YELLOW",
    "task_kind":"general",
    "user_text":"local compile task",
    "qwen_draft":"draft",
    "qwen_revision":"revision",
    "fable_coach":json.dumps({"method_card":{"trigger":"x"}}),
    "final_answer":"final",
    "verifier_before":{"final_contract":{"verdict":"PASS"}},
    "verifier_after":{"final_contract":{"verdict":"PASS"}},
    "verdict":"PASS",
    "proof_path":"",
}
pending = b.training_eligibility(record, b.parse_json_object(record["fable_coach"]), manual_reviewed=False)
assert "manual_review_required" in pending["reasons"], pending
approved = b.training_eligibility(record, b.parse_json_object(record["fable_coach"]), manual_reviewed=True)
assert approved["eligible"], approved
PY
pass "manual_review_gate"

python3 - <<'PY'
import sqlite3
import sentinel_ledger_v5 as s
s.init()
c = sqlite3.connect(s.DB_PATH)
count = c.execute("SELECT COUNT(*) FROM stop_conditions WHERE cleared_at IS NULL").fetchone()[0]
c.close()
assert count == 0
PY
pass "stop_conditions_table_empty"

if [[ "$CHECK_LAUNCHD" == "1" ]]; then
  if ! command -v launchctl >/dev/null 2>&1; then
    fail "launchd unavailable"
  fi
  if grep -R "ASTER_ALLOW_FALLBACK_VERIFIER\\|ASTER_EXPORT_REVIEWED_ONLY=0" ~/Library/LaunchAgents 2>/dev/null; then
    fail "launchd_forbidden_env"
  fi
  pass "launchd_forbidden_env_absent"
else
  echo "SKIP: launchd checks (pass --check-launchd to enforce)"
fi

echo "PASS: accept_v5_install"
