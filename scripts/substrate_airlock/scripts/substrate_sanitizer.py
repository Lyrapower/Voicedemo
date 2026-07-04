#!/usr/bin/env python3
"""Sanitize LM Studio / Qwen responses before Aster sees them.

Pure stdlib. No network. This script strips exposed reasoning fields and
<think> blocks, preserving only final content for the Aster compiler.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any


THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
THINK_OPEN_RE = re.compile(r"<think\b[^>]*>.*$", re.IGNORECASE | re.DOTALL)


REASONING_KEYS = {
    "reasoning_content",
    "reasoning",
    "analysis",
    "thought",
    "thoughts",
    "thinking",
}


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "output_text"} and item.get("text") is not None:
                    parts.append(str(item["text"]))
                elif item.get("content") is not None:
                    parts.append(str(item["content"]))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _extract_message(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        if "choices" in payload and payload["choices"]:
            choice = payload["choices"][0]
            if isinstance(choice, dict) and isinstance(choice.get("message"), dict):
                return choice["message"]
            if isinstance(choice, dict) and isinstance(choice.get("delta"), dict):
                return choice["delta"]
        if "message" in payload and isinstance(payload["message"], dict):
            return payload["message"]
        return payload
    return {"content": str(payload)}


def _strip_think_blocks(content: str) -> tuple[str, list[str]]:
    removed = THINK_RE.findall(content)
    cleaned = THINK_RE.sub("", content)
    dangling = THINK_OPEN_RE.search(cleaned)
    if dangling:
        removed.append(dangling.group(0))
        cleaned = cleaned[: dangling.start()]
    if "</think>" in cleaned.lower():
        parts = re.split(r"</think>", cleaned, flags=re.IGNORECASE)
        removed.append("</think>".join(parts[:-1]))
        cleaned = parts[-1]
    return cleaned.strip(), removed


def _collect_reasoning_fields(obj: Any, path: str = "$") -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}"
            if key in REASONING_KEYS and value not in (None, ""):
                found.append({"path": child_path, "value": _content_to_text(value)})
            else:
                found.extend(_collect_reasoning_fields(value, child_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            found.extend(_collect_reasoning_fields(item, f"{path}[{idx}]"))
    return found


def _extract_stream_events(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("data:"):
            data = stripped[5:].strip()
            if data == "[DONE]":
                continue
            try:
                events.append(json.loads(data))
            except json.JSONDecodeError:
                events.append({"content": data})
    return events


def sanitize_stream_text(raw: str) -> dict[str, Any]:
    events = _extract_stream_events(raw)
    content_parts: list[str] = []
    reasoning_items: list[dict[str, str]] = []
    for event in events:
        reasoning_items.extend(_collect_reasoning_fields(event))
        message = _extract_message(event)
        content_parts.append(_content_to_text(message.get("content")))

    cleaned, think_blocks = _strip_think_blocks("".join(content_parts))
    quarantine = {
        "reasoning_fields": reasoning_items,
        "think_blocks": think_blocks,
        "had_reasoning_leak": bool(reasoning_items or think_blocks),
        "sanitized_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "clean_content": cleaned,
        "quarantine": quarantine,
        "source_shape": "openai_sse_stream",
    }


def sanitize_response(payload: Any) -> dict[str, Any]:
    message = _extract_message(payload)
    content = _content_to_text(message.get("content"))
    reasoning_fields = _collect_reasoning_fields(payload)
    quarantine: dict[str, Any] = {
        "reasoning_content": message.get("reasoning_content"),
        "reasoning": message.get("reasoning"),
        "reasoning_fields": reasoning_fields,
        "think_blocks": [],
        "had_reasoning_leak": False,
        "sanitized_at": datetime.now(timezone.utc).isoformat(),
    }

    cleaned, think_blocks = _strip_think_blocks(content)
    quarantine["think_blocks"] = think_blocks
    quarantine["had_reasoning_leak"] = bool(
        quarantine["reasoning_content"] or quarantine["reasoning"] or reasoning_fields or think_blocks
    )

    return {
        "clean_content": cleaned,
        "quarantine": quarantine,
        "source_shape": "openai_compatible" if isinstance(payload, dict) and "choices" in payload else "message_or_text",
    }


def cmd_sanitize(args: argparse.Namespace) -> int:
    raw = Path(args.input).read_text(encoding="utf-8")
    if raw.lstrip().startswith("data:"):
        result = sanitize_stream_text(raw)
    else:
        try:
            payload: Any = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        result = sanitize_response(payload)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(result["clean_content"].strip() + "\n", encoding="utf-8")

    if args.quarantine:
        Path(args.quarantine).parent.mkdir(parents=True, exist_ok=True)
        Path(args.quarantine).write_text(
            json.dumps(result["quarantine"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print("PASS: sanitized Qwen response")
    print(f"had_reasoning_leak={result['quarantine']['had_reasoning_leak']}")
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "reasoning_content": "hidden chain should not pass",
                    "content": "<think>also hidden</think>\n{\"intent\":\"compile\",\"deliverable\":\"clean\"}",
                }
            }
        ]
    }
    result = sanitize_response(payload)
    assert "hidden" not in result["clean_content"]
    assert result["clean_content"] == '{"intent":"compile","deliverable":"clean"}'
    assert result["quarantine"]["had_reasoning_leak"] is True

    stream = "\n".join(
        [
            'data: {"choices":[{"delta":{"reasoning_content":"hidden stream"}}]}',
            'data: {"choices":[{"delta":{"content":"<think>bad</think>"}}]}',
            'data: {"choices":[{"delta":{"content":"clean"}}]}',
            "data: [DONE]",
        ]
    )
    stream_result = sanitize_stream_text(stream)
    assert stream_result["clean_content"] == "clean"
    assert stream_result["quarantine"]["had_reasoning_leak"] is True

    dangling = sanitize_response({"content": "<think>never closes"})
    assert dangling["clean_content"] == ""
    assert dangling["quarantine"]["had_reasoning_leak"] is True

    print("PASS: substrate_sanitizer selftest")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sanitize = sub.add_parser("sanitize")
    sanitize.add_argument("--input", required=True)
    sanitize.add_argument("--out", required=True)
    sanitize.add_argument("--quarantine")
    sanitize.set_defaults(func=cmd_sanitize)

    selftest = sub.add_parser("selftest")
    selftest.set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
