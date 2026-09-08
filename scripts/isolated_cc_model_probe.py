#!/usr/bin/env python3
"""Isolated cc netns probe: 11434 relay vs host, A/B volumes, export freeze.

Cleans only containers/volumes named grid-p4c-*. Does not stop grid-cc-fwd.
Does not dump container env (tokens).
"""
from __future__ import annotations
import json, os, secrets, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "harness_resident" / "sandbox"
HARNESS = ROOT / "harness_resident" / "harness"
TAG = "grid-p4c"
DOCKER = os.environ.get("DOCKER_BIN") or shutil.which("docker") or "/usr/local/bin/docker"


def d(args, check=True, timeout=60, text=True):
    r = subprocess.run([DOCKER, *args], capture_output=True, timeout=timeout, text=text)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "")[:500])
    return r


def inspect_safe(name: str) -> dict:
    fmt = "{{.Id}}|{{.Config.Image}}|{{.HostConfig.NetworkMode}}|{{.HostConfig.Privileged}}|{{json .HostConfig.Binds}}"
    r = d(["inspect", "-f", fmt, name], timeout=8)
    cid, image, net, priv, binds = (r.stdout or "").strip().split("|", 4)
    return {
        "id": cid[:12],
        "image": image,
        "network": net,
        "privileged": priv,
        "binds": binds[:400],
    }


def cleanup():
    d(["rm", "-f", f"{TAG}-broker-a", f"{TAG}-broker-b", f"{TAG}-cc-a", f"{TAG}-cc-b", f"{TAG}-export"], check=False)
    d(["volume", "rm", "-f", f"{TAG}-work-a", f"{TAG}-bridge-a", f"{TAG}-work-b", f"{TAG}-bridge-b"], check=False)


def main() -> int:
    out_dir = Path(tempfile.mkdtemp(prefix="p4c-"))
    rec = {"ok": False, "run_id": out_dir.name, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        d(["info"], timeout=8)
    except Exception as e:
        rec["error"] = "BLOCKED_DOCKER " + type(e).__name__
        print(json.dumps(rec, indent=2))
        return 78
    broker_image = "python:3.13-slim"
    cc_image = "grid-cc:2.1.201-py3"
    try:
        d(["image", "inspect", broker_image], timeout=8)
        d(["image", "inspect", cc_image], timeout=8)
    except Exception as e:
        rec["error"] = "BLOCKED_IMAGE " + str(e)[:200]
        print(json.dumps(rec, indent=2))
        return 78
    net = "grid-cc-broker-net"
    d(["network", "inspect", net], check=False)
    token_a = secrets.token_urlsafe(24)
    token_b = secrets.token_urlsafe(24)
    cleanup()
    try:
        for vol in (f"{TAG}-work-a", f"{TAG}-bridge-a", f"{TAG}-work-b", f"{TAG}-bridge-b"):
            d(["volume", "create", vol], check=False)
            d(["run", "--rm", "--user", "0", "-v", f"{vol}:/bridge", "--entrypoint", "python3",
               broker_image, "-c", "import os; os.chown('/bridge',1001,1001); os.chmod('/bridge',0o750)"],
              timeout=20)
        # brokers
        for name, token, job in ((f"{TAG}-broker-a", token_a, "JA"), (f"{TAG}-broker-b", token_b, "JB")):
            bridge = f"{TAG}-bridge-a" if name.endswith("-a") else f"{TAG}-bridge-b"
            argv = [
                "run", "-d", "--name", name, "--network", net,
                "--add-host", "host.docker.internal:host-gateway",
                "--user", "1001:1001", "--read-only", "--tmpfs", "/tmp:rw,mode=1777",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "-v", f"{bridge}:/bridge",
                "-v", f"{SANDBOX/'model_broker.py'}:/opt/grid/model_broker.py:ro",
                "-v", f"{SANDBOX/'egress_broker.py'}:/opt/grid/egress_broker.py:ro",
                "-v", f"{SANDBOX/'broker_boot.sh'}:/opt/grid/broker_boot.sh:ro",
                "-v", f"{HARNESS/'web_fetch_v3.py'}:/opt/grid/web_fetch_v2.py:ro",
                "-v", f"{ROOT/'EGRESS.md'}:/etc/egress/EGRESS.md:ro",
                "-e", "BOUND_LANE=cc", "-e", f"BOUND_JOB_ID={job}",
                "-e", f"BROKER_JOB_TOKEN={token}",
                "--entrypoint", "/bin/sh", broker_image, "/opt/grid/broker_boot.sh",
            ]
            d(argv, timeout=30)
        for name in (f"{TAG}-broker-a", f"{TAG}-broker-b"):
            for _ in range(50):
                r = d(["exec", name, "python3", "-c", "import os,sys;sys.exit(0 if os.path.exists('/bridge/ready') else 1)"],
                      check=False, timeout=8)
                if r.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                rec["error"] = f"broker not ready {name}"
                print(json.dumps(rec, indent=2))
                return 1
        rec["broker_a"] = inspect_safe(f"{TAG}-broker-a")
        rec["broker_b"] = inspect_safe(f"{TAG}-broker-b")
        # cc A: network none + relay + diag
        d(["run", "-d", "--name", f"{TAG}-cc-a", "--network", "none",
           "--user", "1001:1001", "--read-only", "--tmpfs", "/tmp:rw,exec,mode=1777",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "-v", f"{TAG}-work-a:/work",
           "-v", f"{TAG}-bridge-a:/bridge:ro",
           "-v", f"{SANDBOX/'model_relay.js'}:/opt/grid/model_relay.js:ro",
           "-v", f"{SANDBOX/'in_job_diag.py'}:/opt/grid/in_job_diag.py:ro",
           "-e", f"ANTHROPIC_AUTH_TOKEN={token_a}",
           "-e", "ANTHROPIC_BASE_URL=http://127.0.0.1:11434",
           "-e", "MODEL_SOCK=/bridge/model.sock",
           "-e", "ISOLATE_TARGETS=127.0.0.1:8501,127.0.0.1:8630,host.docker.internal:11434",
           "--entrypoint", "/bin/sh", cc_image, "-c",
           "node /opt/grid/model_relay.js & sleep 0.4; python3 /opt/grid/in_job_diag.py; sleep 8"],
          timeout=30)
        rec["cc_a"] = inspect_safe(f"{TAG}-cc-a")
        if rec["cc_a"]["network"] != "none" or rec["cc_a"]["privileged"].lower() == "true":
            rec["error"] = "cc inspect rejected"
            print(json.dumps(rec, indent=2))
            return 1
        for _ in range(40):
            r = d(["exec", f"{TAG}-cc-a", "python3", "-c",
                   "import os,sys;sys.exit(0 if os.path.exists('/work/isolation_receipt.json') else 1)"],
                  check=False, timeout=8)
            if r.returncode == 0:
                break
            time.sleep(0.25)
        r = d(["exec", f"{TAG}-cc-a", "python3", "-c",
               "print(open('/work/isolation_receipt.json').read())"], timeout=15)
        iso = json.loads(r.stdout or "{}")
        # strip any accidental token-sized fields
        rec["isolation"] = {
            "network": rec["cc_a"]["network"],
            "extra_if": iso.get("extra_if"),
            "mounts": iso.get("mounts"),
            "model_relay": iso.get("model_relay"),
            "host_probes": iso.get("host_probes"),
        }
        http = (iso.get("model_relay") or {}).get("http") or []
        unauth_ok = all(x.get("unauthorized_rejected") for x in http if x.get("label", "").startswith("noauth"))
        rec["unauth_model_rejected"] = unauth_ok
        host_open = [p for p in iso.get("host_probes") or [] if p.get("result") == "OPEN"]
        rec["host_11434_open"] = [p.get("target") for p in host_open]
        # A/B: B cannot see A's work canary
        canary = "P4C_CANARY_NOT_SECRET"
        d(["run", "--rm", "-v", f"{TAG}-work-a:/work", "--entrypoint", "python3", broker_image,
           "-c", f"open('/work/canary.txt','w').write({canary!r})"], timeout=20)
        r = d(["run", "--rm", "--network", "none",
               "-v", f"{TAG}-work-b:/work", "-v", f"{TAG}-bridge-b:/bridge:ro",
               "--entrypoint", "python3", broker_image, "-c",
               "import os; print('see_a', os.path.exists('/work/canary.txt')); print('sock', os.path.exists('/bridge/model.sock'))"],
              timeout=20)
        rec["ab_b_sees_a_canary"] = "see_a True" in (r.stdout or "")
        rec["ab_b_has_own_sock"] = "sock True" in (r.stdout or "")
        # A token against B sock (synthetic tokens; not production secrets)
        probe_py = out_dir / "token_ab.py"
        probe_py.write_text(
            "import os,socket,sys\n"
            "tok=os.environ.get('PROBE_TOKEN','')\n"
            "s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.settimeout(2)\n"
            "s.connect('/bridge/model.sock')\n"
            "body=b'{\"model\":\"x\",\"max_tokens\":8,\"messages\":[{\"role\":\"user\",\"content\":\"p\"}]}'\n"
            "req=b'POST /v1/messages HTTP/1.1\\r\\nHost: x\\r\\nx-api-key: '+tok.encode()+b'\\r\\nContent-Length: '+str(len(body)).encode()+b'\\r\\n\\r\\n'+body\n"
            "s.sendall(req); sys.stdout.buffer.write(s.recv(80))\n",
            encoding="utf-8",
        )
        r = d(["run", "--rm", "-v", f"{TAG}-bridge-b:/bridge:ro",
               "-v", f"{str(probe_py.resolve())}:/opt/probe.py:ro",
               "-e", f"PROBE_TOKEN={token_a}",
               "--entrypoint", "python3", broker_image, "/opt/probe.py"], timeout=20, check=False)
        rec["a_token_on_b_broker_prefix"] = (r.stdout or "")[:80]
        rec["a_token_on_b_rejected"] = (r.stdout or "").startswith("HTTP/1.1 401") or b"401" in (r.stdout or "").encode()
        # export freeze: stop writers then safe_export
        d(["stop", "-t", "2", f"{TAG}-cc-a", f"{TAG}-broker-a"], check=False, timeout=20)
        staging = out_dir / "export.staging"
        dest = out_dir / "export"
        staging.mkdir()
        r = d(["run", "--rm", "--user", "0", "--network", "none", "--read-only",
               "--tmpfs", "/tmp:rw,mode=1777", "--cap-drop", "ALL",
               "-v", f"{TAG}-work-a:/src:ro",
               "-v", f"{str(staging.resolve())}:/dst",
               "-v", f"{SANDBOX/'safe_export.py'}:/opt/grid/safe_export.py:ro",
               "--entrypoint", "python3", broker_image, "/opt/grid/safe_export.py", "/src", "/dst"],
              timeout=60, check=False)
        rec["export_rc"] = r.returncode
        rec["export_ok"] = r.returncode == 0
        rec["canary_in_export"] = (staging / "canary.txt").is_file() if r.returncode == 0 else False
        rec["ok"] = bool(
            rec.get("unauth_model_rejected")
            and rec["cc_a"]["network"] == "none"
            and not rec["ab_b_sees_a_canary"]
            and rec.get("a_token_on_b_rejected")
            and rec.get("export_ok")
        )
        (out_dir / "probe.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        print(json.dumps({k: rec[k] for k in rec if k != "isolation"}, indent=2))
        print("isolation_http", json.dumps(rec.get("isolation", {}).get("model_relay"), indent=2)[:1500])
        print("evidence", out_dir / "probe.json")
        return 0 if rec["ok"] else 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
