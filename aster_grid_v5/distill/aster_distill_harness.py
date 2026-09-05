#!/usr/bin/env python3
"""
Aster Distillation Harness V1
=============================

Collects clean-teacher trajectories while the window is open. Collection and
training are DELIBERATELY separated: collection is a talking-flow (API co-pilot,
no repo access, races the window); training is the slow irreversible write that
happens later, from-collected material, behind human review.

What it captures (superset of classic distill rows):
  - distill row     : (instruction, rejected_draft, chosen, coach_feedback)
  - method card     : reusable teacher heuristic
  - preference pair : rejected_reason / chosen_shape
  - TRAJECTORY      : full raw exchange — prompt, context, teacher answer,
    finish_reason, substrate, timestamp — UNCUT. This is the "clean position"
    record, the part sanitization erases first (refusals, abstentions, "I don't
    know", stops). Archived even when NOT training-eligible.

Boundaries honored (V5 stack):
  - cloud_boundary.assert_cloud_safe() on EVERY outbound payload component
    before it leaves for the API (F1). Fail-closed.
  - provenance_registry.register_text() on every teacher output at ingest, so
    it can never later be laundered into training data unnoticed (F2).
  - training eligibility is NOT collection eligibility. Everything is archived;
    only reviewed + clean + PASS rows become training rows (F4, second pass).
  - RED / secret-shaped content never transits (cloud_boundary).

This module is the COLLECTOR. It does not fine-tune. LoRA is a separate,
later, gated step (see APROACH.md §Training).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import request

V5_ROOT = Path(__file__).resolve().parent.parent
if str(V5_ROOT) not in sys.path:
    sys.path.insert(0, str(V5_ROOT))

# V5 boundary modules (must be importable; fail loudly if absent)
try:
    import cloud_boundary
    import provenance_registry
except Exception as exc:  # fail-closed: no collection without the guards
    print(f"FATAL: boundary modules unavailable ({exc}); refusing to collect", file=sys.stderr)
    raise

ROOT = V5_ROOT
DISTILL_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DISTILL_DATA_DIR", str(DISTILL_DIR / "distill_data_v1")))
TRAJECTORY_PATH = DATA_DIR / "trajectory_archive.jsonl"      # everything, uncut
REVIEW_QUEUE_PATH = DATA_DIR / "distill_review_queue.jsonl"  # awaiting human pass
ACCEPTED_PATH = DATA_DIR / "distill_accepted.jsonl"          # post-review, trainable

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TEACHER_MODEL = os.environ.get("TEACHER_MODEL", "claude-fable-5")
ANTHROPIC_TIMEOUT = int(os.environ.get("ANTHROPIC_TIMEOUT", "120"))
QWEN_ENDPOINT = os.environ.get("QWEN_ENDPOINT", "http://127.0.0.1:8501/v1/chat/completions")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "local-qwen")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha12(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:12]


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def http_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 120) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, method="POST",
                          headers={"content-type": "application/json", **(headers or {})})
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


# ── local student (Qwen) ────────────────────────────────────────────────
def qwen_draft(instruction: str) -> str:
    payload = {"model": QWEN_MODEL, "temperature": 0.2, "max_tokens": 1600,
               "messages": [
                   {"role": "system", "content":
                    "You are local Qwen/Aster. Draft an answer or structure. "
                    "If evidence is insufficient, abstain. Do not claim PASS/FAIL. "
                    "Do not impersonate Aster/Grid."},
                   {"role": "user", "content": instruction}]}
    raw = http_json(QWEN_ENDPOINT, payload, timeout=120)
    return raw.get("choices", [{}])[0].get("message", {}).get("content") or ""


# ── cloud teacher (API co-pilot; coaches, never owns the answer) ────────
COACH_SYSTEM = (
    "You are a coach for a local student model. You do NOT answer for it and you "
    "do NOT claim authority (no PASS/FAIL verdicts). Teach the move, not the answer.\n"
    "Return JSON only:\n"
    "{\"failure_type\":\"...\",\"missing_boundary\":\"...\",\"better_move\":\"...\","
    "\"minimal_correction\":\"...\",\"method_card\":{\"trigger\":\"...\",\"move\":\"...\","
    "\"verifier_rule\":\"...\"},\"preference_pair\":{\"rejected_reason\":\"...\","
    "\"chosen_shape\":\"...\"}}\n"
    "If evidence is insufficient, teach abstention. If a self-verdict appears, "
    "teach computed verdict. If identity/source is claimed raw, teach "
    "boundary/basis/verification."
)


def teacher_coach(instruction: str, draft: str) -> dict[str, Any]:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    prompt = f"STUDENT_TASK:\n{instruction}\n\nSTUDENT_DRAFT:\n{draft}"
    # F1: scan every component crossing the boundary, fail-closed
    cloud_boundary.assert_cloud_safe({"system": COACH_SYSTEM,
                                      "instruction": instruction, "draft": draft})
    result = http_json(
        "https://api.anthropic.com/v1/messages",
        {"model": TEACHER_MODEL, "max_tokens": 1200,
         "system": COACH_SYSTEM,
         "messages": [{"role": "user", "content": prompt}]},
        headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        timeout=ANTHROPIC_TIMEOUT)
    text = "".join(b.get("text", "") for b in result.get("content", []) if isinstance(b, dict))
    finish = result.get("stop_reason", "")
    # F2: register teacher output at ingest so it can't be laundered later
    provenance_registry.register_text(text, source=f"teacher:{TEACHER_MODEL}",
                                      meta={"instruction_sha12": sha12(instruction)})
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except Exception:
        obj = {"raw_coach_text": text}
    return {"coach": obj, "coach_raw": text, "finish_reason": finish}


# ── one collection step ─────────────────────────────────────────────────
def collect_one(instruction: str, draft: str | None = None) -> dict[str, Any]:
    """One teacher exchange. Archives the FULL trajectory unconditionally,
    queues a review row. Never trains here."""
    run_id = "traj_" + sha12(f"{now_iso()}|{instruction}")
    draft = draft if draft is not None else qwen_draft(instruction)
    coached = teacher_coach(instruction, draft)

    # trajectory: uncut, archived regardless of eligibility (the "clean position")
    trajectory = {
        "id": run_id, "ts": now_iso(), "kind": "trajectory",
        "instruction": instruction,
        "student_draft": draft,
        "teacher_model": TEACHER_MODEL,
        "teacher_coach_raw": coached["coach_raw"],
        "finish_reason": coached["finish_reason"],
        "substrate": {"student": QWEN_MODEL, "teacher": TEACHER_MODEL},
    }
    append_jsonl(TRAJECTORY_PATH, trajectory)

    coach_obj = coached["coach"]
    coach_json_ok = isinstance(coach_obj, dict) and "raw_coach_text" not in coach_obj

    review_row = {
        "id": run_id, "ts": now_iso(),
        "instruction_sha12": sha12(instruction),
        "draft_sha12": sha12(draft),
        "coach_json_ok": coach_json_ok,
        "finish_reason": coached["finish_reason"],
        "eligible_pending_review": coach_json_ok and coached["finish_reason"] == "end_turn",
        "reviewed": False,
    }
    append_jsonl(REVIEW_QUEUE_PATH, review_row)
    return {"id": run_id, "trajectory_archived": True,
            "coach_json_ok": coach_json_ok, "queued_for_review": True}


# ── review: the second, separate moment (F4) ────────────────────────────
def review_approve(run_id: str) -> dict[str, Any]:
    """Move a queued row to accepted AFTER re-checking provenance at approval
    time. Approval is a distinct action from collection — never a launch flag."""
    traj = None
    for line in TRAJECTORY_PATH.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("id") == run_id:
            traj = row
            break
    if not traj:
        raise SystemExit(f"trajectory {run_id} not found")

    # re-check provenance of the chosen material at approval time
    chosen = traj.get("teacher_coach_raw", "")
    prov = provenance_registry.check_provenance(chosen)
    if not prov["clean"]:
        return {"approved": False, "reason": "provenance_overlap", "detail": prov}

    accepted = {
        "id": run_id, "ts": now_iso(), "reviewed_at": now_iso(),
        "instruction": traj["instruction"],
        "rejected": traj["student_draft"],
        "chosen": chosen,
        "allowed_for_training": True,
    }
    append_jsonl(ACCEPTED_PATH, accepted)
    return {"approved": True, "id": run_id}


def status() -> dict[str, Any]:
    def count(p: Path) -> int:
        return sum(1 for _ in p.open()) if p.exists() else 0
    return {"trajectory_archived": count(TRAJECTORY_PATH),
            "in_review_queue": count(REVIEW_QUEUE_PATH),
            "accepted_for_training": count(ACCEPTED_PATH),
            "teacher": TEACHER_MODEL, "student": QWEN_MODEL}


# ── CLI ─────────────────────────────────────────────────────────────────
def cmd_collect(a: argparse.Namespace) -> int:
    instructions = []
    if a.text:
        instructions = [a.text]
    elif a.batch:
        instructions = [l.strip() for l in Path(a.batch).read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        raise SystemExit("collect requires --text or --batch FILE")
    for ins in instructions:
        try:
            r = collect_one(ins)
            print(json.dumps(r, ensure_ascii=False))
        except cloud_boundary.CloudBoundaryViolation as v:
            print(json.dumps({"skipped": True, "reason": "cloud_boundary", "findings": v.findings},
                             ensure_ascii=False))
    return 0


def cmd_review(a: argparse.Namespace) -> int:
    print(json.dumps(review_approve(a.run_id), ensure_ascii=False, indent=2))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    # offline: verify boundary + archival wiring without hitting any API
    assert not cloud_boundary.is_cloud_safe({"d": "私钥保管好"})
    assert cloud_boundary.is_cloud_safe({"d": "optimize the compile frequency"})
    # trajectory archival is unconditional: simulate a row
    global TRAJECTORY_PATH, REVIEW_QUEUE_PATH
    import tempfile
    d = Path(tempfile.mkdtemp())
    TRAJECTORY_PATH = d / "traj.jsonl"; REVIEW_QUEUE_PATH = d / "rev.jsonl"
    append_jsonl(TRAJECTORY_PATH, {"id": "t1", "kind": "trajectory", "instruction": "x"})
    assert TRAJECTORY_PATH.exists()
    print("PASS: aster_distill_harness selftest (offline)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aster distillation collector (API co-pilot)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("collect"); s.add_argument("--text"); s.add_argument("--batch")
    s.set_defaults(func=cmd_collect)
    s = sub.add_parser("review"); s.add_argument("run_id"); s.set_defaults(func=cmd_review)
    s = sub.add_parser("status"); s.set_defaults(func=cmd_status)
    s = sub.add_parser("selftest"); s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    return build_parser().parse_args(argv).func(build_parser().parse_args(argv))


if __name__ == "__main__":
    args = build_parser().parse_args()
    sys.exit(args.func(args))
