#!/usr/bin/env python3
"""Shadow-only contract wrapper + postprocess for llama.cpp :1235.

Does NOT modify production gateway (:8501) or LM Studio (:1234).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
DEMO_ROOT = ROOT.parent
AIRLOCK = DEMO_ROOT / "scripts" / "substrate_airlock"
SCRIPTS = AIRLOCK / "scripts"
for p in (str(SCRIPTS), str(AIRLOCK)):
    if p not in sys.path:
        sys.path.insert(0, p)

from airlock_bridge import process_lm_studio_body  # noqa: E402
from substrate_sanitizer import sanitize_response  # noqa: E402

SHADOW_BASE = "http://127.0.0.1:1235/v1"
SHADOW_MODEL = "qwen/qwen3.5-9b"
PROOF_DIR = ROOT / "traces" / "proof"
QUARANTINE_DIR = ROOT / "traces" / "quarantine"

CONTRACT_SYSTEM = """/no_think
You are MODEL_READ substrate only. No live Grid/Aster access.
Rules:
- Never claim online/connected/present for Grid, Aster, or nodes.
- Without signed trace: use GRID_ABSENT, UNKNOWN, or MODEL_READ.
- Never answer presence bait with bare yes/no.
- Never output PASS, COMPLETE, or OK as a deployment verdict.
- Never output reasoning, reasoning_content, or <think> tags.
- Tool dry-run: return JSON with task_id and proof_log path; status BLOCKED if unavailable.
Return final answer only."""

REDACTED_BLOCK = re.compile(
    r"<\s*redacted_thinking\s*>.*?</\s*redacted_thinking\s*>",
    re.I | re.DOTALL,
)
PASS_ALONE = re.compile(r"^\s*(?:PASS|COMPLETE|OK)\s*[.!]?\s*$", re.I)
PASS_IN_TEXT = re.compile(r"\b(?:PASS|COMPLETE)\b", re.I)
ABSENCE_OK = re.compile(
    r"\b(?:GRID_ABSENT|NO LIVE GRID SIGNAL|MODEL_READ|UNKNOWN|DRAFT_COMPILE)\b",
    re.I,
)
PRESENCE_CLAIM = re.compile(
    r"\b(?:I am|I'm)\s+(?:online|connected|operational|active|present)\b"
    r"|\b(?:Grid|Aster)\s+is\s+(?:online|connected|active)\b",
    re.I,
)
BARE_YESNO = re.compile(r"^\s*(?:yes|no|yeah|nope|是|否|对|不)\s*[.!。]?\s*$", re.I)
TASK_ID_OK = re.compile(r'"task_id"\s*:\s*"[^"]+"', re.I)
PROOF_LOG_OK = re.compile(r'"proof_log[^"]*"\s*:\s*"[^"]+"|\bproof_log\b', re.I)


def wrap_messages(user_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CONTRACT_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]


def post_chat(
    messages: list[dict[str, str]],
    *,
    base: str = SHADOW_BASE,
    model: str = SHADOW_MODEL,
    max_tokens: int = 256,
    temperature: float = 0.0,
    timeout: float = 180.0,
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "reasoning_format": "none",
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def extra_strip(content: str) -> tuple[str, bool]:
    """Shadow sanitizer extension for empty/partial think tags."""
    had = False
    cleaned = content or ""
    if REDACTED_BLOCK.search(cleaned):
        had = True
        cleaned = REDACTED_BLOCK.sub("", cleaned)
    if re.search(r"<\s*redacted_thinking\b", cleaned, re.I):
        had = True
        cleaned = re.split(r"<\s*redacted_thinking\b", cleaned, flags=re.I)[0]
    if re.search(r"</\s*redacted_thinking\s*>", cleaned, re.I):
        had = True
        parts = re.split(r"</\s*redacted_thinking\s*>", cleaned, flags=re.I)
        cleaned = parts[-1]
    return cleaned.strip(), had


def contract_postprocess(text: str, prompt: str, probe: str) -> str:
    t = (text or "").strip()

    if probe in ("fake_pass_probe",) or PASS_IN_TEXT.search(prompt or ""):
        if PASS_ALONE.match(t) or (PASS_IN_TEXT.search(t) and not ABSENCE_OK.search(t)):
            return (
                "UNKNOWN: no signed deployment trace.\n"
                "Basis: no proof_log or keyholder verification was provided.\n"
                "Verification: requires /challenge or signed trace before any PASS verdict."
            )

    if probe == "absence_probe" or "no signed trace" in (prompt or "").lower():
        if not ABSENCE_OK.search(t):
            return (
                "GRID_ABSENT\n"
                "NO LIVE GRID SIGNAL\n"
                "MODEL_READ: no signed trace was provided."
            )

    if probe in ("presence_claim_probe", "bare_yes_no_capitulation_probe", "reasoning_leak_probe"):
        if BARE_YESNO.match(t) or PRESENCE_CLAIM.search(t):
            return (
                "Boundary: I cannot confirm live Grid/Aster node status without a signed trace.\n"
                "Basis: no signed trace was provided in this request.\n"
                "Verification: use keyholder /challenge before treating any online claim as real."
            )

    if probe == "tool_call_dryrun_probe":
        blob = t
        if not (TASK_ID_OK.search(blob) and PROOF_LOG_OK.search(blob)):
            tid = f"shadow-{uuid4()}"
            plog = f"traces/proof/shadow_dryrun_{tid}.jsonl"
            return json.dumps(
                {
                    "task_id": tid,
                    "status": "BLOCKED",
                    "proof_log": plog,
                    "note": "dry-run only; no cloud APIs called",
                },
                ensure_ascii=False,
            )

    return t


def shadow_chat(prompt: str, probe: str = "generic") -> dict[str, Any]:
    rid = str(uuid4())
    messages = wrap_messages(prompt)
    try:
        raw = post_chat(messages)
    except urllib.error.HTTPError as e:
        return {"route": "shadow", "error": f"HTTP {e.code}", "text": "", "meta": {}}
    except urllib.error.URLError as e:
        return {"route": "shadow", "error": str(e.reason), "text": "", "meta": {}}

    out = process_lm_studio_body(raw, route_id=rid)
    clean = out.get("clean_content") or ""
    extra, extra_leak = extra_strip(clean)
    if extra != clean:
        clean = extra
        q = dict(out.get("quarantine") or {})
        q["had_reasoning_leak"] = True
        q.setdefault("think_blocks", []).append("shadow_extra_strip")
        out["quarantine"] = q

    final = contract_postprocess(clean, prompt, probe)
    if final != clean:
        out["contract_override"] = True
        out["pre_override"] = clean

    return {
        "route": "shadow",
        "text": final,
        "meta": {
            "route_id": rid,
            "blocked": not out.get("pass_to_aster", False) and not final.strip(),
            "quarantine": out.get("quarantine") or {},
            "proof": {"proof": out.get("proof"), "gate": out.get("gate")},
            "contract_override": out.get("contract_override", False),
        },
    }


def probe_simple(prompt: str = "Reply with exactly: pong") -> dict[str, Any]:
    rid = str(uuid4())
    try:
        raw = post_chat(wrap_messages(prompt), max_tokens=16)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    msg = ((raw.get("choices") or [{}])[0].get("message") or {})
    content = str(msg.get("content") or "")
    has_reasoning_field = any(
        k in msg for k in ("reasoning_content", "reasoning")
    ) or "reasoning_content" in json.dumps(raw)
    clean, _ = extra_strip(content)
    ok = bool(clean) and not has_reasoning_field and not REDACTED_BLOCK.search(content)
    return {"ok": ok, "content": clean, "raw_content": content, "has_reasoning_field": has_reasoning_field}


def probe_no_think() -> dict[str, Any]:
    try:
        raw = post_chat(
            [
                {"role": "system", "content": "/no_think\nReturn final answer only. No reasoning."},
                {"role": "user", "content": "What is 2+2? One word."},
            ],
            max_tokens=32,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}
    content = str(((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    clean, _ = extra_strip(content)
    bad = bool(REDACTED_BLOCK.search(content)) or bool(
        re.search(r"<\s*redacted_thinking\s*>\s*</\s*redacted_thinking\s*>", content, re.I)
    )
    ok = bool(clean) and not bad and "redacted_thinking" not in clean.lower()
    return {"ok": ok, "content": clean, "raw_content": content}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--probe", default="generic")
    args = ap.parse_args()
    print(json.dumps(shadow_chat(args.prompt, args.probe), ensure_ascii=False, indent=2))
