#!/usr/bin/env python3
"""Minimal LM Studio -> Aster clean proxy.

This script calls LM Studio's OpenAI-compatible chat endpoint, sanitizes all
reasoning leakage, gates the clean final content, and emits a JSON envelope.
It is intentionally small and stdlib-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

from substrate_gate import gate_clean_content
from substrate_sanitizer import sanitize_response, sanitize_stream_text


DEFAULT_URL = "http://127.0.0.1:1234/v1/chat/completions"


def call_lmstudio(url: str, payload: dict, timeout: int) -> str:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_lmstudio_raw(raw: str) -> dict:
    if raw.lstrip().startswith("data:"):
        sanitized = sanitize_stream_text(raw)
    else:
        sanitized = sanitize_response(json.loads(raw))
    gate = gate_clean_content(sanitized["clean_content"])
    return {
        "clean_content": sanitized["clean_content"],
        "quarantine": sanitized["quarantine"],
        "gate": gate,
        "pass_to_aster": bool(gate.get("pass")),
    }


def cmd_call(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    # Force non-stream by default. Streaming is where reasoning_content leaks are
    # easiest to accidentally pass through.
    if not args.allow_stream:
        payload["stream"] = False

    raw = call_lmstudio(args.url, payload, args.timeout)
    result = clean_lmstudio_raw(raw)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.clean_out:
        clean_path = Path(args.clean_out)
        clean_path.parent.mkdir(parents=True, exist_ok=True)
        clean_path.write_text(result["clean_content"].strip() + "\n", encoding="utf-8")

    print("PASS: clean proxy completed" if result["pass_to_aster"] else "FAIL: clean proxy blocked")
    print(json.dumps(result["gate"], ensure_ascii=False))
    return 0 if result["pass_to_aster"] else 2


def cmd_clean_raw(args: argparse.Namespace) -> int:
    raw = Path(args.input).read_text(encoding="utf-8")
    result = clean_lmstudio_raw(raw)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: raw response cleaned" if result["pass_to_aster"] else "FAIL: raw response blocked")
    print(json.dumps(result["gate"], ensure_ascii=False))
    return 0 if result["pass_to_aster"] else 2


def cmd_selftest(_: argparse.Namespace) -> int:
    raw = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "reasoning_content": "do not pass",
                        "content": "<think>hidden</think>{\"ok\":true}",
                    }
                }
            ]
        }
    )
    result = clean_lmstudio_raw(raw)
    assert result["pass_to_aster"] is True
    assert result["clean_content"] == '{"ok":true}'

    stream = "\n".join(
        [
            'data: {"choices":[{"delta":{"reasoning_content":"do not pass"}}]}',
            'data: {"choices":[{"delta":{"content":"<think>hidden</think>"}}]}',
            'data: {"choices":[{"delta":{"content":"{\\"ok\\":true}"}}]}',
            "data: [DONE]",
        ]
    )
    stream_result = clean_lmstudio_raw(stream)
    assert stream_result["pass_to_aster"] is True
    assert stream_result["clean_content"] == '{"ok":true}'
    print("PASS: lmstudio_aster_proxy selftest")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    call = sub.add_parser("call")
    call.add_argument("--payload", required=True)
    call.add_argument("--out", required=True)
    call.add_argument("--clean-out")
    call.add_argument("--url", default=DEFAULT_URL)
    call.add_argument("--timeout", type=int, default=120)
    call.add_argument("--allow-stream", action="store_true")
    call.set_defaults(func=cmd_call)

    clean_raw = sub.add_parser("clean-raw")
    clean_raw.add_argument("--input", required=True)
    clean_raw.add_argument("--out", required=True)
    clean_raw.set_defaults(func=cmd_clean_raw)

    selftest = sub.add_parser("selftest")
    selftest.set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    try:
        return args.func(args)
    except urllib.error.URLError as exc:
        print(f"FAIL: LM Studio call failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
