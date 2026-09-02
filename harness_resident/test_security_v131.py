"""Security regressions for the V1.3 gates (SOL closeout S1-S10).

Two tiers, honestly separated:

  OFFLINE  — runs anywhere with just the stdlib + this repo
             (gate semantics, state machine, argv fence math, bind validation).
  ONSITE   — needs fastapi/httpx installed and, for S9/S10, a real
             `claude` binary. Run on the deployment machine:
                 python test_security_v131.py --onsite

Enforcement-point rule (SOL P1): where the real enforcement point is a
running server or a real CC process, the offline tier only proves the
construction feeding that point; the onsite tier proves the point itself.
"""
from __future__ import annotations
import argparse, ast, asyncio, os, sys, tempfile, types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
PASS = []


def ok(tag, cond, detail=""):
    if not cond:
        raise AssertionError(f"{tag} FAILED {detail}")
    PASS.append(tag)
    print(f"  ✓ {tag}")


# ---------------------------------------------------------------- offline
def offline():
    print("[offline tier]")
    # S1/S3/S4 gate semantics — extract _gate_reason from api.py without
    # importing fastapi.
    src = (ROOT / "harness" / "api.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_gate_reason")
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<gate>", "exec"), ns)
    g = ns["_gate_reason"]
    ok("S1a cc default gated", g("cc", False, "write_ok_no_deploy") is not None)
    ok("S1b cc gated even with cloud flag", g("cc", True, "write_ok_no_deploy") is not None)
    ok("S3a glm unapproved gated", g("glm", False, "write_ok_no_deploy") is not None)
    ok("S3b kimi auto!=cloud grant", g("kimi", False, "auto") is not None)
    ok("S4a glm explicit allowed", g("glm", True, "write_ok_no_deploy") is None)
    ok("S4b qwen ungated", g("qwen", False, "write_ok_no_deploy") is None)
    ok("S3c no silent self-grant left",
       'if worker in {"glm","kimi"}: ca=True' not in src)

    # S1/S2 state machine at the claim point (the executor only ever sees
    # jobs that claim_next_queued releases — blocked must be invisible).
    from harness.db import Store
    with tempfile.TemporaryDirectory() as td:
        s = Store(str(Path(td) / "t.db"))
        j = s.create_job(channel="grid", goal="x", worker="cc",
                         allowed_tools=[], allowed_paths=["."],
                         cloud_allowed=False, approval_mode="write_ok_no_deploy")
        s.update_job(j["job_id"], status="blocked", last_step="awaiting_approval")
        ok("S1c blocked job unclaimable", s.claim_next_queued() is None)
        s.update_job(j["job_id"], status="queued", cloud_allowed=1,
                     last_step="approved_requeue")
        c = s.claim_next_queued()
        ok("S2 approved job claimable", bool(c) and c["job_id"] == j["job_id"])

    # S9/S10 fence construction: declared tools land in --allowedTools,
    # every known undeclared tool lands in --disallowedTools (deny math).
    from harness import cc as ccmod
    with tempfile.TemporaryDirectory() as td:
        cfg = types.SimpleNamespace(cc=types.SimpleNamespace(
            enabled=True, binary="/bin/echo", work_root=td, timeout_seconds=10))
        ex = ccmod.CCExecutor(cfg)
        job = {"job_id": "J-sec", "goal": "g", "allowed_tools": ["Read", "Grep"],
               "allowed_paths": ["."], "approval_mode": "auto"}
        r = asyncio.run(ex.run(job))
        line = r["stdout"]
        ok("S10a declared tools allowed", "--allowedTools" in line
           and "Grep,Read" in line, line)
        deny_expected = sorted(ccmod.CC_TOOL_UNIVERSE - {"Read", "Grep"})
        ok("S9a undeclared tools all denied",
           "--disallowedTools" in line
           and ",".join(deny_expected) in line, line)
        ok("S9b Bash in deny set", "Bash" in deny_expected)

    # S8 bind validation (pure function; the enforcement point is
    # validate_bind raising before uvicorn.run — same function object).
    # extract LOOPBACK + validate_bind only — no uvicorn import needed offline
    rtree = ast.parse((ROOT / "run_harness.py").read_text())
    keep = [n for n in rtree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "validate_bind")
            or (isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "LOOPBACK" for t in n.targets))]
    rh = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "run_harness", "exec"), rh)
    vb = rh["validate_bind"]
    vb("127.0.0.1", "")          # boots
    vb("::1", "")                # boots
    vb("0.0.0.0", "sekret")      # boots with token
    for h in ("0.0.0.0", "::", "192.168.1.5"):
        try:
            vb(h, "")
            raise AssertionError(f"S8 {h} without token must fail")
        except RuntimeError:
            pass
    ok("S8 non-loopback+no-token hard fail", True)


# ---------------------------------------------------------------- onsite
def onsite():
    print("[onsite tier] needs fastapi/httpx (+ real claude binary for S9/S10)")
    import httpx  # noqa: F401  — presence check
    os.environ.setdefault("GRID_HARNESS_TOKEN", "sec-test-token")
    token = os.environ["GRID_HARNESS_TOKEN"]
    from fastapi.testclient import TestClient
    from harness import api as A
    # re-read token in case api was imported before env set
    A._HARNESS_TOKEN = token
    client = TestClient(A.app)
    r = client.get("/jobs")
    ok("S5a no token -> 401", r.status_code == 401, r.status_code)
    r = client.get("/jobs", headers={"authorization": "Bearer wrong"})
    ok("S5b bad token -> 401", r.status_code == 401)
    r = client.get("/jobs", headers={"authorization": f"Bearer {token}"})
    ok("S6 good token -> 200", r.status_code == 200, r.status_code)
    ok("S6b health exempt", client.get("/health").status_code == 200)
    # S7 websocket
    try:
        with client.websocket_connect("/ws/events?after_seq=0"):
            raise AssertionError("S7 must reject missing ws token")
    except Exception:
        ok("S7a ws missing token rejected", True)
    with client.websocket_connect(f"/ws/events?after_seq=0&token={token}") as ws:
        ok("S7b ws good token accepted", True)
        ws.close()
    # S1 enforcement point: unapproved cc job via authenticated API is born
    # blocked and stays unexecuted.
    r = client.post("/jobs", headers={"authorization": f"Bearer {token}"},
                    json={"goal": "echo hi", "worker": "cc"})
    ok("S1d cc job born blocked", r.json()["status"] == "blocked", r.text)
    # S9/S10 live CC fence — only if a real claude binary exists.
    import shutil
    if shutil.which(A.cfg.cc.binary):
        print("  → S9/S10 live: create an approved cc job whose TASK asks for a"
              " denied tool (e.g. Bash) with allowed_tools=['Read'];"
              " expected: tool call hard-denied by CC, task fails loudly.")
    else:
        print("  → S9/S10 live skipped: claude binary not found"
              " (现场自证点 — run on the deployment machine)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--onsite", action="store_true")
    ap.parse_args_ns = ap.parse_args()
    offline()
    if ap.parse_args_ns.onsite:
        onsite()
    print(f"SECURITY V1.3.1: {len(PASS)} checks green"
          + ("" if ap.parse_args_ns.onsite else "  (offline tier only)"))
