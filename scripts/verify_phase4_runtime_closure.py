#!/usr/bin/env python3
"""Phase-4 runtime closure gate.

Modes are mutually exclusive:
  preflight          read-only config/version/tests that do not prove live E2E
  isolated-runtime   real processes/DB/network/fault injection (default for engineering)
  production-smoke   explicit no-funds/no-outbound-new-job checks against live 8501/EGRESS
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "harness_resident"
LOCK = Path(tempfile.gettempdir()) / "verify_phase4_runtime_closure.lock"
MODES = ("preflight", "isolated-runtime", "production-smoke")


def _run(cmd, cwd, timeout=180) -> tuple[int, str]:
    print("+", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-4000:] if len(out) > 4000 else out, flush=True)
    print("exit", p.returncode, flush=True)
    return p.returncode, out


def preflight() -> int:
    rc, _ = _run([sys.executable, "test_provision_grid_store_token.py", "-q"], ROOT / "scripts")
    if rc:
        return rc
    tok = ROOT / "grid-sovereign-runtime" / "config" / "grid_store.token"
    print("token_file", tok.is_file(), "mode_preflight_no_e2e")
    sys.path.insert(0, str(HARNESS / "sandbox"))
    import dev_broker as D
    print("DEV_active_rows", len(D.load_dev(str(ROOT / "DEV.md"))))
    sys.path.insert(0, str(HARNESS / "harness"))
    import github_research_secret as G
    import web_fetch_v3 as W
    print("github_loader", G.load_into_environ()["reason"], "authorized", G.loader_authorized())
    eg = W.load_egress(str(ROOT / "EGRESS.md"))
    ag = eg["rows"].get("api.grants.gov") or {}
    print("api.grants.gov_active", bool(ag.get("active")), "approved_cell", bool(str(ag.get("approved") or "").strip()))
    print("star_active", bool((eg.get("star") or {}).get("active")))
    return 0


def isolated_runtime() -> int:
    tests = [
        (HARNESS / "harness", [sys.executable, "-m", "unittest",
            "test_web_fetch", "test_four_blockers", "test_compile_confirm",
            "test_task_schedule", "test_model_broker", "test_safe_export",
            "test_dev_broker", "test_egress_broker", "-q"]),
        (ROOT / "scripts", [sys.executable, "test_provision_grid_store_token.py", "-q"]),
        (ROOT / "grid-sovereign-runtime", [sys.executable, "-m", "unittest",
            "tests.test_store_token_optional", "-q"]),
    ]
    for cwd, cmd in tests:
        rc, _ = _run(cmd, cwd, timeout=180)
        if rc:
            return rc
    probe = ROOT / "scripts" / "isolated_cc_model_probe.py"
    if probe.is_file():
        rc, _ = _run([sys.executable, str(probe)], ROOT, timeout=180)
        if rc:
            return rc
    return 0


def production_smoke() -> int:
    """Does not create production jobs, diary writes, or fill approvals.

    GRID_STORE_TOKEN is optional (owner 2026-09-08). File presence must not
    enable store auth. This smoke asserts the live default: store_auth off.
    """
    req = urllib.request.Request("http://127.0.0.1:8501/health")
    with urllib.request.urlopen(req, timeout=8) as r:
        health = json.loads(r.read().decode())
    store_auth = str(health.get("store_auth") or "")
    print("store_auth", store_auth, "served_by", health.get("served_by"))
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8501/store/conversations/workbench-b11?limit=1", timeout=8
        ) as r:
            store_code = r.status
            r.read(64)
    except urllib.error.HTTPError as e:
        store_code = e.code
    print("unauth_store_get", store_code)
    if store_auth == "on":
        if store_code != 401:
            print("FAIL store_auth on must 401 without token")
            return 1
    elif store_code != 200:
        print("FAIL optional-token open trust must GET store 200")
        return 1
    reg = urllib.request.Request(
        "http://127.0.0.1:8501/grid/compile/register",
        data=b'{"goal":"x","session_id":"compile"}',
        headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8501"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(reg, timeout=8) as r:
            reg_code = r.status
            r.read(200)
    except urllib.error.HTTPError as e:
        reg_code = e.code
    print("compile_register_no_store_token", reg_code)
    if store_auth == "on" and reg_code != 401:
        print("FAIL store_auth on must 401 compile register")
        return 1
    if store_auth != "on" and reg_code not in {200, 201}:
        print("FAIL optional-token compile register should work without X-Grid-Token")
        return 1
    html = urllib.request.Request("http://127.0.0.1:8501/app/grid.html", method="HEAD")
    with urllib.request.urlopen(html, timeout=8) as r:
        cc = r.headers.get("Cache-Control") or ""
        print("grid_html_cache", cc)
        if "no-store" not in cc.lower():
            return 1
    sys.path.insert(0, str(HARNESS / "harness"))
    import web_fetch_v3 as W
    cat = W.catalog_json_post(
        W.CATALOG_SEARCH2,
        {"rows": 10, "keyword": "open-source software ecosystems eligibility", "oppStatuses": "posted"},
        "scout",
        egress_path=str(ROOT / "EGRESS.md"),
    )
    print("catalog_live", cat.get("status"), cat.get("reason"), cat.get("matched_rule"), cat.get("match_kind"))
    if cat.get("ok"):
        print("FAIL catalog must not succeed via * while exact row pending")
        return 1
    if cat.get("matched_rule") != "api.grants.gov":
        print("FAIL expected matched_rule api.grants.gov")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    for m in MODES:
        g.add_argument(f"--{m}", dest="mode", action="store_const", const=m)
    args = ap.parse_args()
    fd = os.open(str(LOCK), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("locked")
        return 75
    t0 = time.time()
    try:
        print("mode", args.mode, "utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        fn = {"preflight": preflight, "isolated-runtime": isolated_runtime, "production-smoke": production_smoke}[args.mode]
        rc = fn()
        print("elapsed_s", round(time.time() - t0, 2), "exit", rc)
        return rc
    finally:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
