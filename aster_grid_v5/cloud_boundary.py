#!/usr/bin/env python3
"""
Cloud Boundary V5
=================

Single choke-point for any payload that crosses into a cloud/referee boundary
such as Claude Code CLI.

The boundary scans all payload components, not only user text.
It is intentionally conservative for secret-shaped values and less aggressive
for ordinary engineering words such as "token budget".
"""

from __future__ import annotations

import json
import re
from typing import Any


class CloudBoundaryViolation(RuntimeError):
    def __init__(self, findings: list[dict[str, str]]) -> None:
        self.findings = findings
        super().__init__("cloud boundary violation: " + json.dumps(findings, ensure_ascii=False))


VALUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_or_api_key", re.compile(r"\bsk-[A-Za-z0-9]{8,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+\S{8,}", re.I)),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("eth_address_or_hex_secret", re.compile(r"\b0x[0-9a-fA-F]{40,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]

WORD_TERMS = [
    "api key",
    "apikey",
    "secret",
    "token",
    "password",
    "private key",
    "ssh key",
]

CJK_TERMS = ["私钥", "密钥", "密码", "助记词", "红区", "不要上传"]

HARD_TERMS = ["sealed core", "private raw", "no cloud", "RED"]


def flatten_payload(payload: Any, prefix: str = "payload") -> list[tuple[str, str]]:
    if payload is None:
        return []
    if isinstance(payload, str):
        return [(prefix, payload)]
    if isinstance(payload, (int, float, bool)):
        return [(prefix, str(payload))]
    if isinstance(payload, dict):
        out: list[tuple[str, str]] = []
        for key, value in payload.items():
            out.extend(flatten_payload(value, f"{prefix}.{key}"))
        return out
    if isinstance(payload, (list, tuple, set)):
        out = []
        for i, value in enumerate(payload):
            out.extend(flatten_payload(value, f"{prefix}[{i}]"))
        return out
    return [(prefix, str(payload))]


def _mnemonic_like(text: str) -> bool:
    words = re.findall(r"\b[a-z]{3,12}\b", text.lower())
    if len(words) < 12:
        return False
    # Heuristic: 12 or 24 lower-case words near each other with no punctuation-heavy structure.
    for n in (12, 24):
        for i in range(0, max(len(words) - n + 1, 0)):
            span = " ".join(words[i : i + n])
            if len(span) <= n * 13:
                return True
    return False


def find_violations(payload: Any) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for field, text in flatten_payload(payload):
        if not text:
            continue
        low = text.lower()
        for name, pattern in VALUE_PATTERNS:
            if pattern.search(text):
                findings.append({"field": field, "kind": name})
        if _mnemonic_like(text):
            findings.append({"field": field, "kind": "mnemonic_like"})
        for term in CJK_TERMS:
            if term in text:
                findings.append({"field": field, "kind": f"cjk:{term}"})
        for term in HARD_TERMS:
            if term.lower() in low:
                findings.append({"field": field, "kind": f"hard:{term}"})

        for term in WORD_TERMS:
            for match in re.finditer(re.escape(term), low, flags=re.I):
                start = max(0, match.start() - 80)
                end = min(len(text), match.end() + 80)
                window = text[start:end]
                has_assignment = re.search(r"[:=]\s*\S+", window)
                has_value = any(p.search(window) for _, p in VALUE_PATTERNS)
                if has_assignment or has_value:
                    findings.append({"field": field, "kind": f"word_with_value:{term}"})
    # Stable unique findings.
    seen: set[tuple[str, str]] = set()
    unique = []
    for f in findings:
        key = (f["field"], f["kind"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def is_cloud_safe(payload: Any) -> bool:
    return not find_violations(payload)


def assert_cloud_safe(payload: Any) -> None:
    findings = find_violations(payload)
    if findings:
        raise CloudBoundaryViolation(findings)


def selftest() -> None:
    assert not is_cloud_safe({"x": "私钥保管好"})
    assert is_cloud_safe({"x": "auth token budget"})
    assert not is_cloud_safe({"x": "token = sk-abc12345"})
    assert not is_cloud_safe({"user_text": "clean", "qwen_draft": "api_key sk-secret999"})
    assert not is_cloud_safe({"x": "Bearer abcdefghi"})
    assert not is_cloud_safe({"x": "0x" + "a" * 40})


if __name__ == "__main__":
    selftest()
    print("PASS: cloud_boundary selftest")
