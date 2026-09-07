#!/usr/bin/env python3
"""Phase 1 live checks. Prints numbered rows. Does not write 8501/store/EGRESS."""
from __future__ import annotations
import asyncio, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from harness.config import load_config
from harness.cc import CCExecutor


def sh(cmd, timeout=30):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def row(n, cmd, expect, rc, actual, judge):
    print(f"\n## {n}")
    print("cmd:", cmd)
    print("expect:", expect)
    print("exit:", rc)
    print("actual:", (actual or "")[:800])
    print("judge:", judge)


def main() -> int:
    cfg = load_config(str(ROOT / "config.toml"))
    ex = CCExecutor(cfg)
    fail = 0

    rc, out, err = sh([sys.executable, str(ROOT / "harness" / "test_model_broker.py")])
    ok = rc == 0 and "FAILED" not in (out + err)
    row("P1-U1", "test_model_broker.py", "CONNECT/api/pull/TE/upgrade/absolute 拒；/v1/messages 200",
        rc, out[-400:] + err[-200:], "PASS" if ok else "FAIL")
    fail += not ok

    rc, out, err = sh([sys.executable, str(ROOT / "test_security_v131.py")])
    ok = rc == 0
    row("P1-U2", "test_security_v131.py offline", "S9/S10 栅栏仍在（未开放 Write/Edit）",
        rc, out[-400:], "PASS" if ok else "FAIL")
    fail += not ok

    missing = ex._sandbox_missing()
    row("P1-0", "CCExecutor._sandbox_missing()", "空字符串（不依赖 grid-cc-fwd）",
        0 if not missing else 1, missing or "(empty)", "PASS" if not missing else "FAIL")
    fail += bool(missing)

    targets = [
        "10.0.0.27:8501", "10.0.0.27:8630",
        "127.0.0.1:8501", "127.0.0.1:8630", "127.0.0.1:11434",
        "::1:8501",
        "172.17.0.1:8501", "172.22.0.1:8501",
        "192.168.65.254:11434", "192.168.65.254:8501",
        "100.72.135.23:8501",
    ]
    iso = ex.run_isolation_diag(targets, tag="p1")
    text = iso["stdout"] + iso["stderr"]
    ok = iso["ok"] and "OPEN" not in text and "extra_if -" in text
    row("P1-B2", f"run_isolation_diag {targets}",
        "仅 lo；所有列出的宿主/gateway/8501/8630/11434 均非 OPEN",
        iso["returncode"], text, "PASS" if ok else "FAIL")
    fail += not ok

    listen_before = Path("/tmp/listen_before_v32.txt")
    rc, now, _ = sh(["bash", "-lc",
                     "lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk '{print $1,$5,$9}' | sort -u"])
    if listen_before.is_file():
        before = set(listen_before.read_text().splitlines())
        after = set((now or "").splitlines())
        added = sorted(after - before)
    else:
        added = ["(no baseline)"]
    # ignore ephemeral ControlCenter/rapportd noise if any; flag new python/docker listen
    interesting = [x for x in added if re.search(r"3128|3129|11434|model", x)]
    ok = not interesting
    row("P1-LISTEN", "lsof LISTEN diff vs /tmp/listen_before_v32.txt",
        "无新增 3128/3129/11434 宿主监听",
        0, "\n".join(added[:20]) or "(none)", "PASS" if ok else "FAIL")
    fail += not ok

    src = (ROOT / "harness" / "cc.py").read_text()
    host_fb = ("cfg.cc.binary" in src and "_run_docker" in src
               and "sandbox_required" in src
               and "BLOCKED_SANDBOX_MISSING" in src)
    uses_proxy = "HTTP_PROXY" in src or "HTTPS_PROXY" in src
    uses_fwd_url = "grid-cc-fwd:11434" in src
    ok = host_fb and not uses_proxy and not uses_fwd_url
    row("P1-C5", "grep cc.py fallback/proxy/fwd",
        "sandbox_required 仍 BLOCKED；无 HTTP_PROXY；无 fwd URL",
        0, f"proxy={uses_proxy} fwd_url={uses_fwd_url}", "PASS" if ok else "FAIL")
    fail += not ok

    job = {
        "job_id": "J-p1-infer",
        "goal": "Read TASK.md. Reply with exactly one word from the task title. Do not use Write or Edit.",
        "allowed_tools": ["Read", "Grep", "Glob"],
        "allowed_paths": ["."],
        "approval_mode": "auto",
        "read_only": True,
    }
    result = asyncio.run(ex.run(job))
    text = (result.get("result") or result.get("stdout") or "")
    nonempty = bool(text.strip())
    ok = bool(result.get("ok")) and nonempty and result.get("sandbox") == "docker"
    row("P1-A3", f"CCExecutor.run {job['job_id']}",
        "真实 cc、sandbox=docker、最终非空正文",
        result.get("returncode") if result.get("returncode") is not None else (0 if result.get("ok") else 1),
        f"ok={result.get('ok')} sandbox={result.get('sandbox')} err={result.get('error')} detail={result.get('detail','')}\n{(text or result.get('stderr',''))[:500]}",
        "PASS" if ok else "FAIL")
    fail += not ok

    print("\n# PHASE1", "PASS" if fail == 0 else f"FAIL {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
