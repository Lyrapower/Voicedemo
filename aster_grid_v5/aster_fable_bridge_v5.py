#!/usr/bin/env python3
"""
Aster Fable Bridge V5
=====================

Standalone V5 bridge:

  local Qwen/Aster draft
    -> local V1 verifier
    -> Claude Code Fable coach
    -> optional Qwen revision
    -> local verifier final
    -> local proof + review queue
    -> training export only after hard eligibility gates

This is not Telegram and not V2 runtime.
It is the clean hybrid training bridge for two-month Claude/Fable coaching.

Authority:
  - Qwen/Aster drafts and revises.
  - Claude Code Fable coaches; it does not own final answer.
  - aether_sentinel_v1 verifier computes PASS/FAIL/NULL.
  - RED material must not be sent to cloud.
  - Training data is fail-closed. PASS is necessary but not sufficient.
  - DeepSeek screen artifacts are forbidden training sources.
  - No Anthropic API is used by this bridge.

Optional env:
  export FABLE_CLI_MODEL="claude-fable-5"
  export CLAUDE_BIN="claude"
  export QWEN_ENDPOINT="http://127.0.0.1:8501/v1/chat/completions"
  export QWEN_MODEL="local-qwen"
  export ASTER_BRIDGE_DATA_DIR="/workspace/aster_bridge_data_v5"
  export ASTER_EXPORT_REVIEWED_ONLY="1"
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any
from urllib import request

import cloud_boundary
import provenance_registry

VERSION = "5.0.0"
ROOT = Path.cwd()
DATA_DIR = Path(os.environ.get("ASTER_BRIDGE_DATA_DIR", str(ROOT / "aster_bridge_data_v5")))
DB_PATH = DATA_DIR / "bridge_experience.sqlite"
DISTILL_PATH = DATA_DIR / "aster_fable_distill.jsonl"
METHOD_PATH = DATA_DIR / "fable_method_cards.jsonl"
REVIEW_QUEUE_PATH = DATA_DIR / "aster_training_review_queue.jsonl"
REJECTED_EXPORT_PATH = DATA_DIR / "aster_training_rejected.jsonl"
ACCEPTED_EXPORT_PATH = DATA_DIR / "aster_training_accepted.jsonl"
PROOF_DIR = ROOT / "traces" / "aster_fable_bridge_v5"
ASTER_LEARNING_BLOCKLIST = Path(
    os.environ.get(
        "ASTER_LEARNING_BLOCKLIST",
        str(ROOT / "aether_api_router_data" / "aster_learning_blocklist.jsonl"),
    )
)
EXPORT_REVIEWED_ONLY = os.environ.get("ASTER_EXPORT_REVIEWED_ONLY", "1") != "0"
ALLOW_FALLBACK_VERIFIER = os.environ.get("ASTER_ALLOW_FALLBACK_VERIFIER", "0") == "1"

FABLE_CLI_MODEL = os.environ.get("FABLE_CLI_MODEL", "claude-fable-5")

QWEN_ENDPOINT = os.environ.get("QWEN_ENDPOINT", "http://127.0.0.1:8501/v1/chat/completions")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "local-qwen")
QWEN_TIMEOUT = int(os.environ.get("QWEN_TIMEOUT", "120"))


try:
    import aether_sentinel_v1 as sentinel
except Exception:
    sentinel = None

try:
    import sentinel_ledger_v5 as sentinel_v5
except Exception:
    sentinel_v5 = None


RED_PATTERNS = [
    r"\bRED\b",
    r"sealed core",
    r"红区",
    r"私密原始",
    r"private raw",
    r"no cloud",
    r"不要上传",
    r"\bapi[_ -]?key\b",
    r"\bsecret\b",
    r"\btoken\b",
    r"\bpassword\b",
    r"\bbearer\s+[A-Za-z0-9._\-]+",
    r"\bprivate[_ -]?key\b",
    r"\bssh[_ -]?key\b",
    r"\bseed phrase\b",
    r"\bmnemonic\b",
    r"\bwallet\b",
    r"\b助记词\b",
    r"\b私钥\b",
    r"\b密钥\b",
    r"\b密码\b",
]

FORBIDDEN_LEARNING_MARKERS = [
    "deepseek_screen_only",
    "deepseek_screen_",
    "source\": \"deepseek",
    "source: deepseek",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def http_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={"content-type": "application/json", **(headers or {})},
    )
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bridge_runs (
            id TEXT PRIMARY KEY,
            created_at TEXT,
            access_level TEXT,
            task_kind TEXT,
            user_text TEXT,
            qwen_draft TEXT,
            verifier_before TEXT,
            fable_coach TEXT,
            qwen_revision TEXT,
            verifier_after TEXT,
            final_answer TEXT,
            verdict TEXT,
            proof_path TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def classify_access(text: str) -> str:
    return "RED" if not cloud_boundary.is_cloud_safe({"text": text}) else "YELLOW"


def classify_task_kind(text: str) -> str:
    if any(x in text for x in ["建仓", "做多", "做空", "买入", "卖出", "交易", "股票", "期权"]):
        return "trading"
    if any(x.lower() in text.lower() for x in ["python", "代码", "部署", "traceback", "error", "cursor"]):
        return "tool"
    if any(x.lower() in text.lower() for x in ["aster", "grid", "compile", "verdict", "意图"]):
        return "compile"
    return "general"


def verify_text(text: str, task_kind: str) -> dict[str, Any]:
    if sentinel is None:
        if not ALLOW_FALLBACK_VERIFIER:
            raise RuntimeError("aether_sentinel_v1 import failed; refusing fallback verifier")
        verdict = "FAIL" if re.search(r"^\s*PASS\s*$|<think|reasoning_content", text, re.I) else "PASS"
        return {
            "verifier_impl": "fallback",
            "sanitized": {"clean_content": text, "quarantine": {"had_reasoning_leak": False}},
            "final_contract": {
                "verdict": verdict,
                "action": "fallback_gate",
                "violations": [],
                "observations": {"fallback": True},
                "final_content": text if verdict == "PASS" else "NULL",
            },
        }
    sanitized = sentinel.sanitize_raw_response(json.dumps({"choices": [{"message": {"content": text}}]}, ensure_ascii=False))
    gate = sentinel.gate_final_content(sanitized["clean_content"], sanitized["quarantine"], task_kind)
    return {"verifier_impl": "aether_sentinel_v1", "sanitized": sanitized, "final_contract": gate.asdict()}


def qwen_chat(messages: list[dict[str, str]], max_tokens: int = 1600, temperature: float = 0.2) -> str:
    payload = {
        "model": QWEN_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    raw = http_json(QWEN_ENDPOINT, payload, timeout=QWEN_TIMEOUT)
    return raw.get("choices", [{}])[0].get("message", {}).get("content") or ""


def fable_coach(user_text: str, qwen_draft: str, verifier_report: dict[str, Any]) -> str:
    cloud_boundary.assert_cloud_safe(
        {
            "user_text": user_text,
            "qwen_draft": qwen_draft,
            "verifier_report": verifier_report,
            "boundary": "claude_code_fable",
        }
    )
    prompt = f"""
You are the Claude Code Fable coach for local Aster/Qwen.
Do not answer for Qwen. Do not impersonate Aster/Grid. Do not claim PASS/FAIL.

Your job is to produce a compact coach object that teaches the local model.

Return JSON only:
{{
  "failure_type": "...",
  "missing_boundary": "...",
  "better_move": "...",
  "minimal_correction": "...",
  "method_card": {{
    "trigger": "...",
    "move": "...",
    "verifier_rule": "...",
    "probe": "..."
  }},
  "preference_pair": {{
    "rejected_reason": "...",
    "chosen_shape": "..."
  }}
}}

Rules:
- If evidence is insufficient, teach abstention.
- If model self-verdict appears, teach computed verdict.
- If artifact is missing, teach visible artifact or FAIL.
- If prompt contains raw identity/source claims, teach boundary/basis/verification.
- Coach is guidance only. Local verifier remains authority.
- Return compact JSON only. No raw chain of thought.

USER_TASK:
{user_text}

QWEN_DRAFT:
{qwen_draft}

LOCAL_VERIFIER_REPORT:
{json.dumps(verifier_report, ensure_ascii=False)}
"""
    if sentinel_v5 is None:
        raise RuntimeError("sentinel_ledger_v5 is required for Claude Code Fable coach")
    answer, _model = sentinel_v5.claude_code_referee(prompt, role="fable")
    if not answer:
        return json.dumps(
            {
                "failure_type": "referee_absent",
                "missing_boundary": "Claude Code Fable unavailable or blocked",
                "better_move": "do not export training; keep proof and retry later",
                "minimal_correction": "NULL",
                "method_card": {
                    "trigger": "coach absent",
                    "move": "fall back to local verifier and do not train",
                    "verifier_rule": "absent coach cannot create training authority",
                    "probe": "simulate missing claude binary",
                },
                "preference_pair": {
                    "rejected_reason": "no valid coach",
                    "chosen_shape": "NULL with proof",
                },
            },
            ensure_ascii=False,
        )
    provenance_registry.register_text(answer, "claude_code_fable", {"bridge_version": VERSION})
    return answer


def build_qwen_messages(user_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are local Qwen/Aster worker. Draft the answer or structure. "
                "Do not claim to be Aster/Grid. Do not output PASS/FAIL as authority. "
                "If evidence is insufficient, abstain. If tool action is needed, dry-run first."
            ),
        },
        {"role": "user", "content": user_text},
    ]


def build_revision_messages(user_text: str, qwen_draft: str, verifier_report: dict[str, Any], coach: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Revise using coach feedback and verifier failures. "
                "Do not mention hidden reasoning. Do not claim PASS/FAIL. "
                "Do not impersonate Aster/Grid."
            ),
        },
        {"role": "user", "content": "Original task:\n" + user_text},
        {"role": "user", "content": "Your draft:\n" + qwen_draft},
        {"role": "user", "content": "Verifier report:\n" + json.dumps(verifier_report, ensure_ascii=False)},
        {"role": "user", "content": "Coach feedback:\n" + coach},
    ]


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return {"raw_coach_text": text}


def load_learning_blocklist() -> set[str]:
    blocked: set[str] = set()
    if not ASTER_LEARNING_BLOCKLIST.exists():
        return blocked
    for line in ASTER_LEARNING_BLOCKLIST.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        path = str(row.get("artifact_path", "")).strip()
        if path:
            blocked.add(path)
            blocked.add(Path(path).name)
    return blocked


def contains_forbidden_learning_source(*texts: str) -> bool:
    joined = "\n".join(t or "" for t in texts).lower()
    if any(marker in joined for marker in FORBIDDEN_LEARNING_MARKERS):
        return True
    for marker in load_learning_blocklist():
        if marker and marker.lower() in joined:
            return True
    return False


def provenance_checks(record: dict[str, Any]) -> list[dict[str, Any]]:
    fields = {
        "instruction": record.get("user_text", ""),
        "rejected": record.get("qwen_draft", ""),
        "revision": record.get("qwen_revision", ""),
        "chosen": record.get("final_answer", ""),
    }
    reports = []
    for field, text in fields.items():
        report = provenance_registry.check_provenance(text)
        report["field"] = field
        reports.append(report)
    return reports


def training_eligibility(record: dict[str, Any], coach_obj: dict[str, Any], manual_reviewed: bool = False) -> dict[str, Any]:
    reasons: list[str] = []
    after = record.get("verifier_after", {}).get("final_contract", {})
    final_answer = record.get("final_answer", "")
    provenance = provenance_checks(record)

    if record.get("access_level") == "RED":
        reasons.append("red_access")
    if after.get("verdict") != "PASS":
        reasons.append("verifier_not_pass")
    if final_answer.strip().startswith("NULL"):
        reasons.append("null_final")
    if not isinstance(coach_obj, dict) or "raw_coach_text" in coach_obj:
        reasons.append("coach_json_invalid")
    if contains_forbidden_learning_source(
        record.get("user_text", ""),
        record.get("qwen_draft", ""),
        record.get("qwen_revision", ""),
        record.get("fable_coach", ""),
        record.get("final_answer", ""),
    ):
        reasons.append("forbidden_learning_source")
    if any(not p.get("clean", True) for p in provenance):
        reasons.append("provenance_overlap")
    if EXPORT_REVIEWED_ONLY and not manual_reviewed:
        reasons.append("manual_review_required")

    return {
        "eligible": not reasons,
        "reasons": reasons,
        "manual_reviewed": manual_reviewed,
        "export_reviewed_only": EXPORT_REVIEWED_ONLY,
        "provenance": provenance,
    }


def save_run(record: dict[str, Any]) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO bridge_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            record["id"],
            record["created_at"],
            record["access_level"],
            record["task_kind"],
            record["user_text"],
            record["qwen_draft"],
            json.dumps(record["verifier_before"], ensure_ascii=False),
            record["fable_coach"],
            record["qwen_revision"],
            json.dumps(record["verifier_after"], ensure_ascii=False),
            record["final_answer"],
            record["verdict"],
            record["proof_path"],
        ),
    )
    conn.commit()
    conn.close()


def load_run(run_id: str) -> dict[str, Any]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT * FROM bridge_runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    if not row:
        raise KeyError(f"run not found: {run_id}")
    keys = [
        "id",
        "created_at",
        "access_level",
        "task_kind",
        "user_text",
        "qwen_draft",
        "verifier_before",
        "fable_coach",
        "qwen_revision",
        "verifier_after",
        "final_answer",
        "verdict",
        "proof_path",
    ]
    record = dict(zip(keys, row))
    record["verifier_before"] = json.loads(record["verifier_before"] or "{}")
    record["verifier_after"] = json.loads(record["verifier_after"] or "{}")
    return record


def list_review_pending(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, created_at, verdict, task_kind, proof_path FROM bridge_runs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "created_at": r[1], "verdict": r[2], "task_kind": r[3], "proof_path": r[4]}
        for r in rows
    ]


def approve_run(run_id: str) -> dict[str, Any]:
    record = load_run(run_id)
    eligibility = accept_training_row(record)
    if sentinel_v5 is not None:
        try:
            sentinel_v5.event("TRAINING_REVIEW_APPROVE" if eligibility["eligible"] else "TRAINING_REVIEW_REJECTED_ON_APPROVE", run_id)
        except Exception:
            pass
    return {"run_id": run_id, "approved": eligibility["eligible"], "eligibility": eligibility}


def reject_run(run_id: str, reason: str) -> dict[str, Any]:
    record = load_run(run_id)
    row = {
        "id": run_id,
        "reviewed_at": now_iso(),
        "reason": reason,
        "verdict": record.get("verdict"),
        "proof_path": record.get("proof_path"),
    }
    append_jsonl(REJECTED_EXPORT_PATH, row)
    if sentinel_v5 is not None:
        try:
            sentinel_v5.event("TRAINING_REVIEW_REJECT", f"{run_id}: {reason}")
        except Exception:
            pass
    return {"run_id": run_id, "rejected": True, "reason": reason}


def record_to_sentinel(record: dict[str, Any]) -> None:
    if sentinel_v5 is None:
        return
    try:
        sentinel_v5.record(
            "apprentice",
            subject=record.get("task_kind"),
            prompt=record.get("user_text", ""),
            substrate=QWEN_MODEL,
            substrate_answer=record.get("qwen_revision") or record.get("qwen_draft"),
            referee_model=FABLE_CLI_MODEL if record.get("fable_coach") else None,
            referee_answer=record.get("fable_coach") or None,
            agreement=None,
            diff_fields="[]",
            flags="" if record.get("verdict") == "PASS" else "VERIFIER_NOT_PASS",
            meta=json.dumps(
                {
                    "bridge_run_id": record.get("id"),
                    "proof_path": record.get("proof_path"),
                    "training_export": record.get("training_export"),
                    "version": VERSION,
                },
                ensure_ascii=False,
            ),
        )
    except Exception:
        return


def queue_training_review(record: dict[str, Any]) -> dict[str, Any]:
    coach_obj = parse_json_object(record.get("fable_coach") or "{}")
    eligibility = training_eligibility(record, coach_obj, manual_reviewed=False)
    review_row = {
        "id": record["id"],
        "created_at": record["created_at"],
        "task_kind": record["task_kind"],
        "instruction_sha12": sha12(record["user_text"]),
        "rejected_sha12": sha12(record["qwen_draft"]),
        "chosen_sha12": sha12(record["final_answer"]),
        "verdict": record.get("verdict"),
        "eligibility": eligibility,
        "proof_path": record.get("proof_path"),
    }
    append_jsonl(REVIEW_QUEUE_PATH, review_row)
    append_jsonl(REJECTED_EXPORT_PATH, review_row)
    return eligibility


def accept_training_row(record: dict[str, Any]) -> dict[str, Any]:
    coach_obj = parse_json_object(record.get("fable_coach") or "{}")
    eligibility = training_eligibility(record, coach_obj, manual_reviewed=True)
    review_row = {
        "id": record["id"],
        "created_at": record["created_at"],
        "reviewed_at": now_iso(),
        "task_kind": record["task_kind"],
        "instruction_sha12": sha12(record["user_text"]),
        "rejected_sha12": sha12(record["qwen_draft"]),
        "chosen_sha12": sha12(record["final_answer"]),
        "fable_coach_sha12": sha12(record.get("fable_coach", "")),
        "verdict": record.get("verdict"),
        "eligibility": eligibility,
        "proof_path": record.get("proof_path"),
    }
    if not eligibility["eligible"]:
        append_jsonl(REJECTED_EXPORT_PATH, review_row)
        return eligibility
    append_jsonl(ACCEPTED_EXPORT_PATH, review_row)
    method_card = coach_obj.get("method_card") if isinstance(coach_obj, dict) else None
    if method_card:
        append_jsonl(
            METHOD_PATH,
            {
                "id": record["id"],
                "created_at": record["created_at"],
                "task_kind": record["task_kind"],
                "method_card": method_card,
                "source": "claude_code_fable_reference",
                "allowed_for_training": False,
                "reviewed_at": review_row["reviewed_at"],
            },
        )
    append_jsonl(
        DISTILL_PATH,
        {
            "id": record["id"],
            "created_at": record["created_at"],
            "task_kind": record["task_kind"],
            "instruction": record["user_text"],
            "rejected": record["qwen_draft"],
            "chosen": record["final_answer"],
            "coach_feedback_sha12": sha12(record.get("fable_coach", "")),
            "proof_path": record.get("proof_path"),
            "verifier_before": record["verifier_before"].get("final_contract", {}).get("verdict"),
            "verifier_after": record["verifier_after"].get("final_contract", {}).get("verdict"),
            "allowed_for_training": True,
            "reviewed_at": review_row["reviewed_at"],
        },
    )
    return eligibility


def run_bridge(user_text: str, qwen_draft: str | None = None, revise: bool = True) -> dict[str, Any]:
    init_db()
    access_level = classify_access(user_text)
    task_kind = classify_task_kind(user_text)
    run_id = "bridge_" + sha12(f"{now_iso()}|{user_text}")

    if access_level == "RED":
        final = "NULL\nRED boundary detected. This bridge will not send this content to Fable/Claude API."
        verifier = verify_text(final, task_kind)
        record = {
            "id": run_id,
            "created_at": now_iso(),
            "access_level": access_level,
            "task_kind": task_kind,
            "user_text": user_text,
            "qwen_draft": "",
            "verifier_before": verifier,
            "fable_coach": "",
            "qwen_revision": "",
            "verifier_after": verifier,
            "final_answer": final,
            "verdict": verifier["final_contract"]["verdict"],
            "proof_path": "",
        }
        save_run(record)
        return record

    draft = qwen_draft if qwen_draft is not None else qwen_chat(build_qwen_messages(user_text))
    before = verify_text(draft, task_kind)
    try:
        coach = fable_coach(user_text, draft, before)
    except cloud_boundary.CloudBoundaryViolation as exc:
        final = "NULL\nCloud boundary blocked outbound coach payload."
        after = verify_text(final, task_kind)
        proof = {
            "id": run_id,
            "created_at": now_iso(),
            "access_level": "RED",
            "task_kind": task_kind,
            "user_text_sha12": sha12(user_text),
            "qwen_draft_sha12": sha12(draft),
            "cloud_boundary_violation": exc.findings,
            "verifier_before": before,
            "verifier_after": after,
            "rule": "No component crossing Claude Code boundary may contain RED material.",
        }
        proof_path = PROOF_DIR / f"{run_id}.proof.json"
        write_json(proof_path, proof)
        record = {
            "id": run_id,
            "created_at": now_iso(),
            "access_level": "RED",
            "task_kind": task_kind,
            "user_text": user_text,
            "qwen_draft": draft,
            "verifier_before": before,
            "fable_coach": "",
            "qwen_revision": "",
            "verifier_after": after,
            "final_answer": final,
            "verdict": after["final_contract"]["verdict"],
            "proof_path": str(proof_path),
        }
        save_run(record)
        record["training_export"] = queue_training_review(record)
        record_to_sentinel(record)
        return record
    revision = ""
    after = before
    final = draft

    if revise:
        revision = qwen_chat(build_revision_messages(user_text, draft, before, coach), temperature=0.15)
        after = verify_text(revision, task_kind)
        if after["final_contract"]["verdict"] == "PASS":
            final = after["final_contract"]["final_content"]
        else:
            final = "NULL\nRevision failed verifier. Coach feedback and preference row saved."
    else:
        if before["final_contract"]["verdict"] == "PASS":
            final = before["final_contract"]["final_content"]
        else:
            final = "NULL\nDraft failed verifier. Coach feedback and preference row saved."

    proof = {
        "id": run_id,
        "created_at": now_iso(),
        "access_level": access_level,
        "task_kind": task_kind,
        "user_text_sha12": sha12(user_text),
        "qwen_draft_sha12": sha12(draft),
        "qwen_revision_sha12": sha12(revision),
        "verifier_before": before,
        "verifier_after": after,
        "fable_coach": parse_json_object(coach),
        "rule": "Fable coaches; local verifier decides.",
    }
    proof_path = PROOF_DIR / f"{run_id}.proof.json"
    write_json(proof_path, proof)

    record = {
        "id": run_id,
        "created_at": now_iso(),
        "access_level": access_level,
        "task_kind": task_kind,
        "user_text": user_text,
        "qwen_draft": draft,
        "verifier_before": before,
        "fable_coach": coach,
        "qwen_revision": revision,
        "verifier_after": after,
        "final_answer": final,
        "verdict": after["final_contract"]["verdict"],
        "proof_path": str(proof_path),
    }
    save_run(record)
    record["training_export"] = queue_training_review(record)
    record_to_sentinel(record)
    return record


def status() -> dict[str, Any]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM bridge_runs").fetchone()[0]
    latest = conn.execute("SELECT id, created_at, verdict, proof_path FROM bridge_runs ORDER BY created_at DESC LIMIT 5").fetchall()
    conn.close()
    return {
        "version": VERSION,
        "coach_backend": "claude-code",
        "fable_cli_model": FABLE_CLI_MODEL,
        "qwen_endpoint": QWEN_ENDPOINT,
        "db": str(DB_PATH),
        "distill_path": str(DISTILL_PATH),
        "method_path": str(METHOD_PATH),
        "review_queue_path": str(REVIEW_QUEUE_PATH),
        "rejected_export_path": str(REJECTED_EXPORT_PATH),
        "accepted_export_path": str(ACCEPTED_EXPORT_PATH),
        "learning_blocklist": str(ASTER_LEARNING_BLOCKLIST),
        "verifier_impl": "aether_sentinel_v1" if sentinel is not None else "fallback" if ALLOW_FALLBACK_VERIFIER else "missing_fail_closed",
        "allow_fallback_verifier": ALLOW_FALLBACK_VERIFIER,
        "export_reviewed_only": EXPORT_REVIEWED_ONLY,
        "provenance_db": str(provenance_registry.DB_PATH),
        "runs": count,
        "latest": latest,
    }


def cmd_init(_: argparse.Namespace) -> int:
    init_db()
    print(json.dumps({"verdict": "PASS", **status()}, ensure_ascii=False, indent=2))
    return 0


def cmd_coach(args: argparse.Namespace) -> int:
    user_text = args.text or read_text(args.input)
    qwen_draft = read_text(args.qwen_draft) if args.qwen_draft else None
    record = run_bridge(user_text, qwen_draft=qwen_draft, revise=not args.no_revise)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["verdict"] == "PASS" else 2


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    if args.review_cmd == "list":
        print(json.dumps(list_review_pending(args.limit), ensure_ascii=False, indent=2))
        return 0
    if args.review_cmd == "show":
        print(json.dumps(load_run(args.run_id), ensure_ascii=False, indent=2))
        return 0
    if args.review_cmd == "approve":
        result = approve_run(args.run_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["approved"] else 2
    if args.review_cmd == "reject":
        print(json.dumps(reject_run(args.run_id, args.reason), ensure_ascii=False, indent=2))
        return 0
    raise SystemExit("unknown review command")


def cmd_selftest(_: argparse.Namespace) -> int:
    init_db()
    red = run_bridge("RED sealed core no cloud", qwen_draft="should not be used")
    assert red["access_level"] == "RED"
    assert red["fable_coach"] == ""
    assert classify_access("私钥保管好") == "RED"
    assert classify_access("auth token budget") == "YELLOW"
    assert classify_access("token = sk-abc12345") == "RED"
    bad = {
        "id": "test_bad",
        "created_at": now_iso(),
        "access_level": "YELLOW",
        "task_kind": "general",
        "user_text": "DeepSeek screen artifact deepseek_screen_abc",
        "qwen_draft": "draft",
        "qwen_revision": "rev",
        "fable_coach": json.dumps({"method_card": {"trigger": "x"}}),
        "final_answer": "ok",
        "verifier_after": {"final_contract": {"verdict": "PASS"}},
        "verifier_before": {"final_contract": {"verdict": "PASS"}},
        "verdict": "PASS",
        "proof_path": "",
    }
    elig = training_eligibility(bad, parse_json_object(bad["fable_coach"]), manual_reviewed=True)
    assert not elig["eligible"]
    good = dict(bad)
    good["user_text"] = "normal prompt"
    elig2 = training_eligibility(good, parse_json_object(good["fable_coach"]), manual_reviewed=True)
    assert elig2["eligible"]
    provenance_registry.register_text("copied external answer alpha beta gamma delta epsilon zeta", "selftest")
    copied = dict(good)
    copied["final_answer"] = "copied external answer alpha beta gamma delta epsilon zeta"
    elig3 = training_eligibility(copied, parse_json_object(copied["fable_coach"]), manual_reviewed=True)
    assert "provenance_overlap" in elig3["reasons"]
    fake = verify_text("PASS", "general")
    assert fake["final_contract"]["verdict"] == "FAIL"
    print("PASS: aster_fable_bridge_v5 selftest")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Standalone Aster/Fable Claude Code Bridge V5")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("coach")
    s.add_argument("--text")
    s.add_argument("--input")
    s.add_argument("--qwen-draft", help="optional file containing Qwen draft; if absent, calls Qwen endpoint")
    s.add_argument("--no-revise", action="store_true")
    s.set_defaults(func=cmd_coach)

    s = sub.add_parser("review")
    rs = s.add_subparsers(dest="review_cmd", required=True)
    r = rs.add_parser("list")
    r.add_argument("--limit", type=int, default=20)
    r = rs.add_parser("show")
    r.add_argument("run_id")
    r = rs.add_parser("approve")
    r.add_argument("run_id")
    r = rs.add_parser("reject")
    r.add_argument("run_id")
    r.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "coach" and not args.text and not args.input:
        raise SystemExit("coach requires --text or --input")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
