#!/usr/bin/env python3
"""Independent smoke test — Ollama Cloud Kimi K2.6 via local :11434 proxy.

Logs thinking metadata only (present/length/hash), never thinking text.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "kimi-k2.6:cloud"


def _post(endpoint: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _thinking_meta(body: dict) -> dict:
    msg = body.get("message") if isinstance(body.get("message"), dict) else {}
    parts = []
    for key in ("thinking", "reasoning_content", "reasoning"):
        val = msg.get(key) or body.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    thinking = "\n".join(parts)
    out = {"thinking_present": bool(thinking), "thinking_length": len(thinking)}
    if thinking:
        out["thinking_hash"] = hashlib.sha256(thinking.encode("utf-8")).hexdigest()[:16]
    return out


def _log_result(label: str, body: dict) -> int:
    msg = body.get("message") if isinstance(body.get("message"), dict) else {}
    content = str(msg.get("content") or "").strip()
    meta = _thinking_meta(body)
    record = {
        "test": label,
        "model": body.get("model"),
        "done_reason": body.get("done_reason"),
        "content_len": len(content),
        "content_preview": content[:120],
        **meta,
    }
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if not content:
        print(f"FAIL {label}: empty content", file=sys.stderr)
        return 1
    # Ensure we never accidentally logged thinking text
    thinking_blob = json.dumps(record)
    for key in ("thinking", "reasoning_content"):
        val = msg.get(key)
        if isinstance(val, str) and val and val in thinking_blob:
            print(f"FAIL {label}: thinking leaked into log", file=sys.stderr)
            return 1
    print(f"PASS {label}")
    return 0


def _tiny_png_b64() -> str:
    # 1x1 red PNG
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    return base64.b64encode(raw).decode("ascii")


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke test kimi-k2.6:cloud via Ollama")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    text_payload = {
        "model": args.model,
        "stream": False,
        "think": True,
        "options": {"num_predict": 512},
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: KIMI_SMOKE_OK",
            }
        ],
    }

    img_payload = {
        "model": args.model,
        "stream": False,
        "think": True,
        "options": {"num_predict": 512},
        "messages": [
            {
                "role": "user",
                "content": "This is a 1x1 test image. Reply with exactly: KIMI_IMG_OK",
                "images": [_tiny_png_b64()],
            }
        ],
    }

    rc = 0
    try:
        rc |= _log_result("text", _post(args.endpoint, text_payload))
        rc |= _log_result("image", _post(args.endpoint, img_payload))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body).get("error", body)
        except json.JSONDecodeError:
            err = body
        print(json.dumps({"error": exc.code, "detail": str(err)[:500]}, indent=2), file=sys.stderr)
        if exc.code == 403 and "subscription" in str(err).lower():
            print("HINT: kimi-k2.6:cloud requires Ollama Pro — https://ollama.com/pricing", file=sys.stderr)
        return 1
    except OSError as exc:
        print(json.dumps({"error": type(exc).__name__, "reason": str(exc)}, indent=2), file=sys.stderr)
        return 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
