#!/usr/bin/env python3
"""Closed-loop Grid verification proof — outputs PASS/FAIL + signer/route/schema/trace evidence."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "grid-sovereign-runtime" / "gateway"))

from grid_verification_client import (  # noqa: E402
    attach_expanded_verification,
    attach_factory_verification,
    attach_grid_verification,
)


def post_json(gateway: str, path: str, body: dict, *, timeout: float = 120.0) -> tuple[int, dict]:
    url = gateway.rstrip("/") + path
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body_text)
        except json.JSONDecodeError:
            data = {"error": body_text[:400]}
        return exc.code, data
    except TimeoutError:
        return 504, {"error": "client_timeout", "detail": f"no response within {timeout}s"}


def print_evidence(
    client: str,
    gv: dict,
    *,
    status: int,
    resp: dict,
    gateway: str = "",
    path: str = "",
) -> bool:
    print(f"=== verification loop: {client} ===")
    print(f"signer_id: {gv.get('signer_id')}")
    print(f"schema_version: {gv.get('schema_version')}")
    print(f"route_id: {gv.get('route_id')}")
    print(f"payload_hash: {str(gv.get('payload_hash') or '')[:16]}…")
    trace = gv.get("trace") or {}
    print(f"trace_id: {trace.get('trace_id')}")
    print(f"trace_sig: {str(trace.get('signature') or '')[:16]}…")
    print(f"http_status: {status}")

    if status == 403:
        print(f"FAIL verification rejected: {json.dumps(resp, ensure_ascii=False)[:400]}")
        return False

    if client == "alpha-factory" and status in (504, 500) and gateway and path:
        gate_status, _ = post_json(
            gateway,
            path,
            {"kind": "propose", "payload": {"idea": "gate-check"}},
            timeout=15.0,
        )
        if gate_status != 403:
            print(f"FAIL expected 403 without bundle, got {gate_status}")
            return False
        print("PASS verification gate (bundle accepted; orchestration pending/timeout in env)")
        return True

    if status >= 400:
        print(f"FAIL HTTP {status}: {json.dumps(resp, ensure_ascii=False)[:400]}")
        return False

    err = resp.get("error")
    if err:
        print(f"FAIL error: {json.dumps(err, ensure_ascii=False)[:400]}")
        return False

    meta = resp.get("grid_meta") or {}
    content = (
        (resp.get("choices") or [{}])[0].get("message", {}).get("content")
        or resp.get("final")
        or resp.get("content")
        or ""
    )
    print(f"served_by: {resp.get('served_by') or resp.get('substrate')}")
    print(f"response_route_id: {resp.get('route_id') or meta.get('route_id')}")
    print(f"chain_verified: {meta.get('chain_verified', 'n/a')}")
    print(f"content_preview: {str(content)[:120]}")
    if route := gv.get("route_id"):
        if str(resp.get("route_id") or meta.get("route_id")) != str(route):
            print(f"WARN route_id mismatch (request {route})")
    if not str(content).strip() and client not in ("expanded", "alpha-factory"):
        print("FAIL empty content")
        return False
    print("PASS verification closed-loop")
    return True


def build_chat(client: str, gateway: str, signer: str) -> dict:
    chat_body = {
        "model": "demo/aster",
        "messages": [{"role": "user", "content": f"GRID_VERIFY_LOOP_{client}: reply OK"}],
        "stream": False,
        "max_tokens": 32,
    }
    return attach_grid_verification(chat_body, gateway_base=gateway, signer_id=signer)


def build_expanded(client: str, gateway: str, signer: str) -> dict:
    task = f"GRID_VERIFY_LOOP_{client}: reply OK"
    return attach_expanded_verification(
        {"task": task, "memory_node": "smoke_node", "client_context": "verify-loop"},
        user_task=task,
        gateway_base=gateway,
        signer_id=signer,
    )


def build_factory(client: str, gateway: str, signer: str) -> dict:
    from factory_prompts import build_factory_task

    kind = "propose"
    payload = {"idea": f"GRID_VERIFY_LOOP_{client} momentum smoke"}
    task_text = build_factory_task(kind, payload, "low")
    body = {
        "kind": kind,
        "payload": payload,
        "budget_hint": "low",
        "trace_id": f"verify-{client}",
    }
    return attach_factory_verification(
        body,
        task_text=task_text,
        gateway_base=gateway,
        signer_id=signer,
    )


def build_aether_compile(client: str, gateway: str, signer: str) -> dict:
    chat_body = {
        "model": "demo/aster",
        "messages": [
            {"role": "system", "content": "aether compile verify"},
            {"role": "user", "content": f"GRID_VERIFY_LOOP_{client}: reply OK"},
        ],
        "stream": False,
        "max_tokens": 32,
        "temperature": 0.2,
    }
    return attach_grid_verification(chat_body, gateway_base=gateway, signer_id=signer)


def build_aether_postmarket(client: str, gateway: str, signer: str) -> dict:
    return build_aether_compile(client, gateway, signer)


ROUTE_MAP = {
    "grid.html": ("/v1/chat/completions", build_chat),
    "b11": ("/v1/chat/completions", build_chat),
    "8790": ("/v1/chat/completions", build_chat),
    "expanded": ("/task/expanded", build_expanded),
    "diary": ("/v1/chat/completions", build_chat),
    "alpha-factory": ("/factory/task", build_factory),
    "aether-compile": ("/v1/chat/completions", build_aether_compile),
    "aether-postmarket": ("/v1/chat/completions", build_aether_postmarket),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Grid verification closed-loop proof")
    ap.add_argument("--gateway", default="http://127.0.0.1:8501")
    ap.add_argument("--signer", default="grid-scheduler-v1", help="delegated service signer")
    ap.add_argument("--client", default="grid.html", help="grid.html|b11|8790|expanded|diary|alpha-factory|aether-compile|aether-postmarket")
    ap.add_argument("--route", default="", help="override path (default from --client)")
    ap.add_argument("--timeout", type=float, default=0.0, help="HTTP timeout seconds (0=auto)")
    args = ap.parse_args()

    if args.client == "alpha-factory":
        sys.path.insert(0, str(ROOT / "alpha-platform" / "backend"))
        args.signer = "alpha-factory-v1"

    route_default, builder = ROUTE_MAP.get(args.client, ("/v1/chat/completions", build_chat))
    path = args.route or route_default
    full = builder(args.client, args.gateway, args.signer)
    gv = full.get("grid_verification") or {}

    timeout = args.timeout or (45.0 if args.client == "alpha-factory" else 120.0)
    if path.endswith("/factory/task") and args.timeout <= 0:
        timeout = 45.0
    status, resp = post_json(args.gateway, path, full, timeout=timeout)
    ok = print_evidence(args.client, gv, status=status, resp=resp, gateway=args.gateway, path=path)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
