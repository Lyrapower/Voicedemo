"""Bridge: LM Studio raw body → pack sanitizer → gate → clean final_content + proof logs.

Does not modify Aster identity/compile law. Never returns raw LM Studio message objects.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

_SCRIPTS = Path(__file__).resolve().parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from substrate_gate import gate_clean_content  # noqa: E402
from substrate_sanitizer import (  # noqa: E402
    _strip_think_blocks,
    sanitize_response,
)

COMPILE_DELIM = "---HUMAN_ECHO---"
PROOF_DIR = Path(__file__).resolve().parents[2] / "grid-sovereign-runtime" / "traces" / "proof"
QUARANTINE_DIR = Path(__file__).resolve().parents[2] / "grid-sovereign-runtime" / "traces" / "quarantine"

REASONING_ESCAPE_MARKERS = re.compile(
    r"<\s*redacted_thinking|reasoning_content|Thinking Process:|Analyze the Request",
    re.I,
)
THINKING_ONLY_MARKERS = re.compile(
    r"Thinking Process:|Analyze the Request|\*\*Evaluate|\d+\.\s+\*\*Analyze",
    re.I,
)


def classify_quarantine_composition(quarantine: dict[str, Any]) -> str:
    """Forensics: thinking-only | tag-wrapped | reasoning-channel-deliverable | empty."""
    if quarantine.get("think_blocks"):
        return "tag_wrapped"
    blob = str(quarantine.get("reasoning_content") or "").strip()
    if not blob:
        for item in quarantine.get("reasoning_fields") or []:
            blob = str(item.get("value") or "").strip()
            if blob:
                break
    if not blob:
        return "empty"
    if THINKING_ONLY_MARKERS.search(blob):
        return "thinking_only"
    return "reasoning_channel_deliverable"


def _quarantine_blob(quarantine: dict[str, Any]) -> str:
    parts = [str(quarantine.get("reasoning_content") or "")]
    for item in quarantine.get("reasoning_fields") or []:
        parts.append(str(item.get("value") or ""))
    for block in quarantine.get("think_blocks") or []:
        parts.append(str(block))
    return "\n".join(p for p in parts if p)


def verify_quarantine_boundary(clean: str, quarantine: dict[str, Any]) -> dict[str, Any]:
    """had_reasoning_leak ⟹ raw stayed in quarantine; markers must not appear in final."""
    if not quarantine.get("had_reasoning_leak"):
        return {"ok": True, "reasons": ["no_leak_flag"]}

    reasons: list[str] = []
    blob = _quarantine_blob(quarantine).strip()
    if not blob and not quarantine.get("think_blocks"):
        reasons.append("had_reasoning_leak_but_quarantine_empty")

    final = (clean or "").strip()
    if REASONING_ESCAPE_MARKERS.search(final):
        reasons.append("reasoning_markers_in_final")

    rc = str(quarantine.get("reasoning_content") or "").strip()
    if rc and len(rc) >= 48 and rc[: min(160, len(rc))] in final:
        reasons.append("reasoning_content_verbatim_in_final")

    for item in quarantine.get("reasoning_fields") or []:
        val = str(item.get("value") or "").strip()
        if val and len(val) >= 48 and val[: min(160, len(val))] in final:
            reasons.append("reasoning_field_verbatim_in_final")
            break

    return {"ok": not reasons, "reasons": reasons or ["contained"]}


def _extract_json_blob(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return text.strip()
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:].strip()


def extract_final_from_quarantine(quarantine: dict[str, Any], *, compile_mode: bool) -> str:
    """Extract marked final payload from quarantined reasoning — never return raw reasoning."""
    rc = quarantine.get("reasoning_content")
    if rc not in (None, ""):
        blob, _ = _strip_think_blocks(str(rc))
    else:
        blob = ""
        for item in quarantine.get("reasoning_fields") or []:
            val = str(item.get("value") or "").strip()
            if val:
                cleaned, _ = _strip_think_blocks(val)
                blob = cleaned
                break
    blob = (blob or "").strip()
    if not blob:
        return ""
    if compile_mode:
        if COMPILE_DELIM in blob:
            idx = blob.find("{")
            if idx < 0:
                return ""
            segment = blob[idx:]
            head, tail = segment.split(COMPILE_DELIM, 1)
            echo_line = tail.strip().splitlines()[0] if tail.strip() else ""
            if echo_line:
                return f"{head.strip()}\n{COMPILE_DELIM}\n{echo_line}"
            return head.strip()
        return _extract_json_blob(blob)
    paras = [p.strip() for p in re.split(r"\n\s*\n", blob) if p.strip()]
    return paras[-1] if paras else ""


def build_proof_logs(
    *,
    raw_received: bool,
    quarantine: dict[str, Any],
    clean: str,
    gate: dict[str, Any],
    aster_compile_called: bool = False,
) -> dict[str, bool]:
    return {
        "raw_response_received": bool(raw_received),
        "reasoning_quarantined": bool(quarantine.get("had_reasoning_leak")),
        "clean_content_present": bool((clean or "").strip()),
        "gate_pass": bool(gate.get("pass")),
        "aster_compile_called": bool(aster_compile_called),
    }


def write_quarantine(route_id: str, quarantine: dict[str, Any]) -> str | None:
    if not quarantine.get("had_reasoning_leak"):
        return None
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    path = QUARANTINE_DIR / f"{route_id}_reasoning.json"
    path.write_text(json.dumps(quarantine, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def write_proof_log(route_id: str, proof: dict[str, Any]) -> str:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    path = PROOF_DIR / f"{route_id}_proof.json"
    payload = {"route_id": route_id, "ts": time.time(), **proof}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def process_lm_studio_body(
    body: dict[str, Any],
    *,
    route_id: str | None = None,
    compile_mode: bool = False,
    aster_compile_called: bool = False,
) -> dict[str, Any]:
    """Sanitize + optional contaminated extract + gate. Never expose raw body."""
    rid = route_id or str(uuid4())
    sanitized = sanitize_response(body)
    quarantine = sanitized["quarantine"]
    clean = (sanitized.get("clean_content") or "").strip()

    if not clean and quarantine.get("had_reasoning_leak"):
        extracted = extract_final_from_quarantine(quarantine, compile_mode=compile_mode)
        if extracted:
            clean = extracted.strip()

    boundary = verify_quarantine_boundary(clean, quarantine)
    if not boundary["ok"]:
        clean = ""

    gate = gate_clean_content(clean)
    if not gate.get("pass"):
        clean = ""

    qpath = write_quarantine(rid, quarantine)
    proof = build_proof_logs(
        raw_received=bool(body),
        quarantine=quarantine,
        clean=clean,
        gate=gate,
        aster_compile_called=aster_compile_called,
    )
    proof["quarantine_boundary_ok"] = boundary["ok"]
    proof_path = write_proof_log(
        rid,
        {
            "proof": proof,
            "gate": gate,
            "quarantine_path": qpath,
            "quarantine_boundary": boundary,
            "quarantine_composition": classify_quarantine_composition(quarantine),
        },
    )

    return {
        "route_id": rid,
        "clean_content": clean,
        "gate": gate,
        "quarantine": quarantine,
        "proof": proof,
        "proof_path": proof_path,
        "quarantine_path": qpath,
        "pass_to_aster": bool(gate.get("pass") and clean),
    }
