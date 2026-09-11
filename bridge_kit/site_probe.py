"""site_probe — 现状核对一条命令(只读)。把 §1 的十条 grep/curl 变成一份报告,戌贴报告原文,不再手拼。

用法(在 repo 根目录):
  python3 bridge_kit/site_probe.py --repo . --egress EGRESS.md --stream <Grid 输入流文件或空> \
      --gateway local_gateway.py --h1 <H1 解析模块路径或空> --theta-src <v6.1 目录或文件> --config-8501 <8501 config>

每项独立:够不着的写 NOT_REACHABLE / NOT_FOUND,不崩、不猜、不改任何文件。密钥只报"有/无",不报值。
零依赖,3.9 语法。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

JIDS = ["J-b5050da341d7", "J-dcc3623e086d", "J-0f9f1853fb58"]


def sh(cmd, cwd=None, timeout=20):
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"rc": p.returncode, "out": p.stdout.strip()[:4000], "err": p.stderr.strip()[:500]}
    except Exception as e:  # noqa
        return {"rc": -1, "out": "", "err": str(e)}


def grep_file(path, pattern, max_lines=40):
    if not path or not os.path.exists(path):
        return {"status": "NOT_FOUND", "path": path}
    hits = []
    rx = re.compile(pattern)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if rx.search(line):
                hits.append("%d:%s" % (i, line.rstrip()[:200]))
                if len(hits) >= max_lines:
                    break
    return {"status": "OK", "path": path, "hits": hits, "n": len(hits)}


def grep_tree(root, pattern, max_lines=60):
    if not root or not os.path.exists(root):
        return {"status": "NOT_FOUND", "path": root}
    rx = re.compile(pattern)
    hits = []
    paths = [root] if os.path.isfile(root) else [
        os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".py")]
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if rx.search(line):
                        hits.append("%s:%d:%s" % (p, i, line.rstrip()[:160]))
                        if len(hits) >= max_lines:
                            return {"status": "OK", "hits": hits, "n": len(hits), "truncated": True}
        except OSError:
            continue
    return {"status": "OK", "hits": hits, "n": len(hits)}


def http(url, method="GET", body=None, timeout=5):
    try:
        req = Request(url, data=(body.encode() if body else None), method=method,
                      headers={"Content-Type": "application/json"} if body else {})
        with urlopen(req, timeout=timeout) as r:
            return {"status": r.getcode(), "body": r.read(400).decode("utf-8", "replace")}
    except HTTPError as e:
        return {"status": e.code, "body": e.read(400).decode("utf-8", "replace")}
    except URLError as e:
        return {"status": "NOT_REACHABLE", "err": str(e.reason)[:120]}
    except Exception as e:  # noqa
        return {"status": "NOT_REACHABLE", "err": str(e)[:120]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--egress", default="EGRESS.md")
    ap.add_argument("--stream", default="")
    ap.add_argument("--gateway", default="local_gateway.py")
    ap.add_argument("--h1", default="")
    ap.add_argument("--theta-src", default="")
    ap.add_argument("--config-8501", default="")
    ap.add_argument("--no-net", action="store_true", help="跳过本机 http 探测(沙箱用)")
    a = ap.parse_args(argv)
    R = {"probe": "site_probe v1", "cwd": os.getcwd()}

    R["git"] = {"head": sh("git rev-parse --short HEAD", a.repo),
                "dirty": sh("git status --porcelain | head -40", a.repo)}
    R["gateway_inbound"] = grep_file(os.path.join(a.repo, a.gateway), r"inbound|input_stream|outbox|h1")
    R["stream_has_jids"] = grep_file(a.stream, "|".join(JIDS)) if a.stream else {"status": "NOT_GIVEN"}
    R["h1_mission_route"] = grep_file(a.h1, r"type:MISSION|proposed|seed") if a.h1 else {"status": "NOT_GIVEN"}
    R["theta_api_version"] = grep_tree(a.theta_src, r"/v2/|root=|25510|25503|/v3/|at_time") if a.theta_src else {"status": "NOT_GIVEN"}
    R["cloud_slots_8501"] = grep_file(a.config_8501, r"running_max|queue_max") if a.config_8501 else {"status": "NOT_GIVEN"}
    R["egress_rows"] = grep_file(os.path.join(a.repo, a.egress),
                                 r"api\.github\.com|html\.duckduckgo\.com|api\.grants\.gov|ollama\.com|api\.search\.brave\.com")
    R["env_keys"] = {k: ("SET" if os.environ.get(k) else "UNSET") for k in ("OLLAMA_API_KEY", "BRAVE_API_KEY", "GITHUB_TOKEN")}
    if a.no_net:
        R["net"] = "SKIPPED"
    else:
        R["net"] = {
            "8630_missions": http("http://127.0.0.1:8630/api/missions"),
            "8630_tools": http("http://127.0.0.1:8630/tools"),
            "11434_web_search_proxy": http("http://127.0.0.1:11434/api/web_search", "POST", '{"query":"x"}'),
            "theta_mdds": http("http://127.0.0.1:25503/v3/terminal/mdds/status"),
        }
    print(json.dumps(R, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
