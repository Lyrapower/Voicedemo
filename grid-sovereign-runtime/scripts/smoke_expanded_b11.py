#!/usr/bin/env python3
"""Smoke: APIs on :8501, workbench UI on :8515, grid.html untouched."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

GW = "http://127.0.0.1:8501"
WB = "http://127.0.0.1:8515"


def get(base: str, path: str) -> int:
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{GW}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    fails = 0
    if get(GW, "/health") != 200:
        print("[FAIL] :8501 health"); fails += 1
    else:
        print("[PASS] :8501 health")
    if get(WB, "/grid_workbench_b11.html") != 200:
        print("[FAIL] :8515 b11 ui"); fails += 1
    else:
        print("[PASS] :8515 b11 ui")
    if get(GW, "/app/grid.html") != 200:
        print("[FAIL] grid app"); fails += 1
    else:
        print("[PASS] grid app on :8501")
    r = post("/task/expanded", {"task": "只回复:ok", "client_context": ""})
    ok = r.get("provenance", {}).get("orchestrator") == "8501"
    print(f"[{'PASS' if ok else 'FAIL'}] /task/expanded orchestrator=8501")
    return 1 if fails or not ok else 0


if __name__ == "__main__":
    sys.exit(main())
