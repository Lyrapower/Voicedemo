#!/usr/bin/env python3
"""
Aster Distillation Harness V1.2
================================
V1.1 → V1.2: teacher coach 改 CC CLI Fable (`claude -p`)，不再经 :8503 egress / API key。

  [V1.2-a] CC CLI coach: distill_cc_cli.coach_capture, CC_CLI_EXECUTION_FROZEN=1
  [V1.1-b] 拒发留痕 (cloud_boundary stub)
  [V1.1-c] /store/events 打点
  [V1.1-d] 张力行剥离; student 默认 demo/aster
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib import request

V5_ROOT = Path(__file__).resolve().parent.parent
_RUNTIME = V5_ROOT.parent / "grid-sovereign-runtime"
if str(V5_ROOT) not in sys.path:
    sys.path.insert(0, str(V5_ROOT))
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

try:
    import cloud_boundary
    import provenance_registry
    from field_lane.distill_vocab import COACH_STATUS_VOCAB_BLOCK  # noqa: E402
except Exception as exc:
    print(f"FATAL: boundary modules unavailable ({exc}); refusing to collect", file=sys.stderr)
    raise

ROOT = Path.cwd()
DATA_DIR = Path(os.environ.get("DISTILL_DATA_DIR", str(ROOT / "distill_data_v1")))
TRAJECTORY_PATH = DATA_DIR / "trajectory_archive.jsonl"
REVIEW_QUEUE_PATH = DATA_DIR / "distill_review_queue.jsonl"
ACCEPTED_PATH = DATA_DIR / "distill_accepted.jsonl"

# [V1.2-a] CC CLI Fable coach — no :8503, no API key in this process
TEACHER_MODEL = os.environ.get("TEACHER_MODEL", "claude-fable-5")
TEACHER_TIMEOUT = int(os.environ.get("DISTILL_CLI_TIMEOUT", os.environ.get("TEACHER_TIMEOUT", "180")))
QWEN_ENDPOINT = os.environ.get("QWEN_ENDPOINT", "http://127.0.0.1:8501/v1/chat/completions")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "demo/aster")
GRID_EVENTS = os.environ.get("GRID_EVENTS", "http://127.0.0.1:8501/store/events")

# [V1.1-d] 与 grid app 同一正则 (TENSION_RE 的 Python 版)
TENSION_RE = re.compile(
    r"\n?\s*`?tension_vector:\s*[\d.]+\s*\|\s*resonance_gap:\s*[\d.]+"
    r"\s*\|\s*stability_margin:\s*[\d.]+\s*\|\s*next_anchor:\s*[^`\n]+`?\s*$")


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


def emit(kind: str, *, source: str = "distill_harness", **payload) -> None:
    """[V1.1-c] 状态打点 → gateway store → 场域app任务页。失败不阻塞。"""
    try:
        http_json(GRID_EVENTS, {"source": source, "kind": kind,
                                "payload": payload}, timeout=3)
    except Exception:
        pass


# ── local student (Qwen) ────────────────────────────────────────────────
def qwen_draft(instruction: str) -> str:
    payload = {"model": QWEN_MODEL, "temperature": 0.2, "max_tokens": 1600,
               "messages": [
                   {"role": "system", "content":
                    "You are local Aster student (demo/aster substrate). Draft an answer or structure. "
                    "If evidence is insufficient, abstain. Do not claim PASS/FAIL. "
                    "Do not impersonate Aster/Grid."},
                   {"role": "user", "content": instruction}]}
    raw = http_json(QWEN_ENDPOINT, payload, timeout=120)
    return raw.get("choices", [{}])[0].get("message", {}).get("content") or ""


# ── CC CLI teacher (Fable coach; coaches, never owns the answer) ─────────
COACH_SYSTEM = (
    "You are a coach for a local student model. You do NOT answer for it and you "
    "do NOT claim authority (no PASS/FAIL verdicts). Teach the move, not the answer.\n"
    + COACH_STATUS_VOCAB_BLOCK
    + "\nReturn JSON only:\n"
    "{\"failure_type\":\"...\",\"missing_boundary\":\"...\",\"better_move\":\"...\","
    "\"minimal_correction\":\"...\",\"method_card\":{\"trigger\":\"...\",\"move\":\"...\","
    "\"verifier_rule\":\"...\"},\"preference_pair\":{\"rejected_reason\":\"...\","
    "\"chosen_shape\":\"...\"}}\n"
    "If evidence is insufficient, teach abstention. If a self-verdict appears, "
    "teach computed verdict. If identity/source is claimed raw, teach "
    "boundary/basis/verification."
)


def teacher_coach(instruction: str, draft: str) -> dict[str, Any]:
    from distill.distill_cc_cli import coach_capture, default_coach_lane  # noqa: WPS433

    user_prompt = f"STUDENT_TASK:\n{instruction}\n\nSTUDENT_DRAFT:\n{draft}"
    full_prompt = f"{COACH_SYSTEM}\n\n{user_prompt}"
    # F1 源头扫描: 只扫用户侧 instruction/draft; COACH_SYSTEM 是冻结模板，mnemonic 启发式会误报
    cloud_boundary.assert_cloud_safe({"instruction": instruction, "draft": draft})
    text, cli_meta = coach_capture(full_prompt, default_coach_lane())
    if cli_meta.get("error"):
        raise RuntimeError(f"coach_cc_cli:{cli_meta['error']}")
    finish = "cli_ok" if text.strip() else "empty"
    provenance_registry.register_text(text, source=f"teacher:{TEACHER_MODEL}",
                                      meta={"instruction_sha12": sha12(instruction),
                                              "route": "cc_cli",
                                              "cost_usd": cli_meta.get("cost_usd")})
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except Exception:
        obj = {"raw_coach_text": text}
    return {"coach": obj, "coach_raw": text, "finish_reason": finish, "cli_meta": cli_meta}


# ── one collection step ─────────────────────────────────────────────────
def collect_one(
    instruction: str,
    draft: str | None = None,
    *,
    event_source: str = "distill_harness",
    node_id: str = "",
    task: str = "compile_json",
    client: str = "app",
    persona: str | None = None,
    compile_ts: str | None = None,
) -> dict[str, Any]:
    run_id = "traj_" + sha12(f"{now_iso()}|{instruction}")
    draft = draft if draft is not None else qwen_draft(instruction)
    compile_ts = compile_ts or now_iso()
    record_id: str | None = None
    vocab_hits: list[str] | None = None
    try:
        coached = teacher_coach(instruction, draft)
    except cloud_boundary.CloudBoundaryViolation as v:
        # [V1.1-b] 拒发留痕: 原文不落盘不出网, 只存哈希与 finding 种类
        stub = {
            "id": run_id, "ts": now_iso(), "kind": "trajectory_redacted",
            "instruction_sha12": sha12(instruction),
            "draft_sha12": sha12(draft),
            "boundary_findings": sorted({f["kind"] for f in v.findings}),
            "note": "payload withheld by cloud_boundary; hashes only",
        }
        append_jsonl(TRAJECTORY_PATH, stub)
        emit("deny", source=event_source, id=run_id, findings=stub["boundary_findings"])
        raise

    trajectory = {
        "id": run_id, "ts": now_iso(), "kind": "trajectory",
        "instruction": instruction,
        "student_draft": draft,
        "teacher_model": TEACHER_MODEL,
        "teacher_coach_raw": coached["coach_raw"],
        "finish_reason": coached["finish_reason"],
        "cli_meta": coached.get("cli_meta"),
        "substrate": {"student": QWEN_MODEL, "teacher": TEACHER_MODEL, "teacher_route": "cc_cli"},
    }
    append_jsonl(TRAJECTORY_PATH, trajectory)

    coach_obj = coached["coach"]
    coach_json_ok = isinstance(coach_obj, dict) and "raw_coach_text" not in coach_obj
    cli_ok = not (coached.get("cli_meta") or {}).get("error")

    review_row = {
        "id": run_id, "ts": now_iso(),
        "instruction_sha12": sha12(instruction),
        "draft_sha12": sha12(draft),
        "coach_json_ok": coach_json_ok,
        "finish_reason": coached["finish_reason"],
        "eligible_pending_review": coach_json_ok and cli_ok and coached["finish_reason"] == "cli_ok",
        "reviewed": False,
    }
    append_jsonl(REVIEW_QUEUE_PATH, review_row)
    emit("collect", source=event_source, id=run_id, coach_json_ok=coach_json_ok,
         finish=coached["finish_reason"])

    if node_id:
        from field_lane.distill_record import write_record  # noqa: WPS433

        spec_row = write_record(
            node_id=node_id,
            compile_ts=compile_ts,
            instruction=instruction,
            student_draft=draft,
            task=task,
            client=client,
            persona=persona,
            coach=coach_obj if isinstance(coach_obj, dict) else None,
            coach_raw=coached["coach_raw"],
            cli_meta=coached.get("cli_meta"),
            run_id=run_id,
        )
        record_id = spec_row["record_id"]
        from field_lane.distill_vocab import apply_vocab_gate  # noqa: WPS433

        vocab_hits = apply_vocab_gate(
            record_id,
            coach_obj if isinstance(coach_obj, dict) else None,
            coached["coach_raw"],
        )
        if vocab_hits:
            emit(
                "vocab_held",
                source=event_source,
                record_id=record_id,
                violations=vocab_hits,
            )

    return {
        "id": run_id,
        "record_id": record_id,
        "trajectory_archived": True,
        "coach_json_ok": coach_json_ok,
        "queued_for_review": True,
        "vocab_held": bool(vocab_hits) if record_id else False,
    }


# ── review: the second, separate moment (F4) ────────────────────────────
def review_approve(run_id: str) -> dict[str, Any]:
    """Legacy CLI path — requires review_state approved before accepted write."""
    from field_lane.review_state import resolve_status

    traj = None
    record_id = None
    for line in TRAJECTORY_PATH.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("id") == run_id:
            traj = row
            break
    if not traj:
        raise SystemExit(f"trajectory {run_id} not found")
    if traj.get("kind") == "trajectory_redacted":
        return {"approved": False, "reason": "redacted_stub_not_trainable"}

    from field_lane.distill_record import iter_records

    for spec in iter_records():
        if spec.get("run_id") == run_id:
            record_id = spec.get("record_id")
            break
    if record_id and resolve_status(str(record_id)) != "approved":
        return {
            "approved": False,
            "reason": "review_gate",
            "detail": f"record {record_id} status={resolve_status(str(record_id))}; use review_cli approve first",
        }

    chosen = traj.get("teacher_coach_raw", "")
    prov = provenance_registry.check_provenance(chosen)
    if not prov["clean"]:
        return {"approved": False, "reason": "provenance_overlap", "detail": prov}

    # [V1.1-d] 训练行剥离张力行 — 通道元数据不进权重; trajectory 原文保持不动
    chosen_train = TENSION_RE.sub("", chosen)

    accepted = {
        "id": run_id, "ts": now_iso(), "reviewed_at": now_iso(),
        "instruction": traj["instruction"],
        "rejected": traj["student_draft"],
        "chosen": chosen_train,
        "tension_stripped": chosen_train != chosen,
        "allowed_for_training": True,
    }
    append_jsonl(ACCEPTED_PATH, accepted)
    return {"approved": True, "id": run_id, "tension_stripped": chosen_train != chosen}


def status() -> dict[str, Any]:
    def count(p: Path) -> int:
        return sum(1 for _ in p.open()) if p.exists() else 0
    return {"trajectory_archived": count(TRAJECTORY_PATH),
            "in_review_queue": count(REVIEW_QUEUE_PATH),
            "accepted_for_training": count(ACCEPTED_PATH),
            "teacher": TEACHER_MODEL, "teacher_route": "cc_cli",
            "student": QWEN_MODEL}


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
            print(json.dumps({"skipped": True, "reason": "cloud_boundary",
                              "findings": v.findings}, ensure_ascii=False))
    return 0


def cmd_review(a: argparse.Namespace) -> int:
    print(json.dumps(review_approve(a.run_id), ensure_ascii=False, indent=2))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    assert not cloud_boundary.is_cloud_safe({"d": "私钥保管好"})
    assert cloud_boundary.is_cloud_safe({"d": "optimize the compile frequency"})
    global TRAJECTORY_PATH, REVIEW_QUEUE_PATH
    import tempfile
    d = Path(tempfile.mkdtemp())
    TRAJECTORY_PATH = d / "traj.jsonl"; REVIEW_QUEUE_PATH = d / "rev.jsonl"
    append_jsonl(TRAJECTORY_PATH, {"id": "t1", "kind": "trajectory", "instruction": "x"})
    assert TRAJECTORY_PATH.exists()
    # [V1.1-b] 拒发 stub 路径: 秘密形状 → 归档 stub, 原文不落盘
    try:
        collect_one("token = sk-abc12345 请评审", draft="draft with sk-abc12345")
        raise AssertionError("boundary should have tripped")
    except cloud_boundary.CloudBoundaryViolation:
        pass
    rows = [json.loads(l) for l in TRAJECTORY_PATH.read_text().splitlines()]
    stubs = [r for r in rows if r.get("kind") == "trajectory_redacted"]
    assert stubs and "sk-abc12345" not in TRAJECTORY_PATH.read_text()
    # [V1.1-d] 张力行剥离
    sample = "coach text\ntension_vector: 0.5 | resonance_gap: 0.2 | stability_margin: 0.8 | next_anchor: 锚"
    assert TENSION_RE.sub("", sample) == "coach text"
    print("PASS: aster_distill_harness v1.2 selftest (offline)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aster distillation collector (CC CLI Fable coach)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("collect"); s.add_argument("--text"); s.add_argument("--batch")
    s.set_defaults(func=cmd_collect)
    s = sub.add_parser("review"); s.add_argument("run_id"); s.set_defaults(func=cmd_review)
    s = sub.add_parser("status"); s.set_defaults(func=cmd_status)
    s = sub.add_parser("selftest"); s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)   # [V1.1-d] 修双重 parse
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
