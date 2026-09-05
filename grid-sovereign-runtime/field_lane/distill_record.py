"""Distill record store — spec DISTILL REVIEW GATE v1 (2026-07-17)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _REPO / "traces" / "distill"
RECORDS_PATH = Path(os.environ.get("DISTILL_RECORDS_PATH", str(_DEFAULT_DIR / "distill_records.jsonl")))
DAILY_CAP = int(os.environ.get("FIELD_DISTILL_DAILY_CAP", "10"))


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_record_id(*, node_id: str, compile_ts: str, fable_response_hash: str) -> str:
    payload = f"{node_id}|{compile_ts}|{fable_response_hash}"
    return _sha256(payload)


def fable_response_hash(coach_raw: str | None) -> str:
    return _sha256(coach_raw or "")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _record_date(row: dict[str, Any]) -> str | None:
    ts = row.get("compile_ts") or row.get("ts")
    if not isinstance(ts, str) or len(ts) < 10:
        return None
    return ts[:10]


def iter_records(*, path: Path | None = None) -> Iterator[dict[str, Any]]:
    p = path or RECORDS_PATH
    if not p.is_file():
        return
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_record(record_id: str, *, path: Path | None = None) -> dict[str, Any] | None:
    for row in iter_records(path=path):
        if row.get("record_id") == record_id:
            return row
    return None


def load_records(*, on_date: str | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in iter_records(path=path):
        if on_date and _record_date(row) != on_date:
            continue
        out.append(row)
    return out


def fable_calls_on_date(day: str, *, path: Path | None = None) -> int:
    n = 0
    for row in iter_records(path=path):
        if _record_date(row) != day:
            continue
        if row.get("skip_reason") == "budget":
            continue
        if row.get("coach") is not None:
            n += 1
    return n


def fable_calls_today(*, path: Path | None = None) -> int:
    day = dt.date.today().isoformat()
    return fable_calls_on_date(day, path=path)


def at_daily_cap(*, path: Path | None = None) -> bool:
    return fable_calls_today(path=path) >= max(0, DAILY_CAP)


def coach_comment_preview(record: dict[str, Any], limit: int = 60) -> str:
    coach = record.get("coach")
    if isinstance(coach, dict):
        for key in ("better_move", "minimal_correction", "failure_type", "raw_coach_text"):
            val = coach.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:limit]
        raw = record.get("coach_raw")
        if isinstance(raw, str):
            return raw.strip()[:limit]
    if record.get("skip_reason") == "budget":
        return "[budget skip — no Fable call]"
    return ""


def fable_grade(record: dict[str, Any]) -> str:
    coach = record.get("coach")
    if not isinstance(coach, dict):
        return "—"
    for key in ("grade", "failure_type"):
        val = coach.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:24]
    return "ok" if coach else "—"


def write_record(
    *,
    node_id: str,
    compile_ts: str,
    instruction: str,
    student_draft: str,
    task: str = "compile_json",
    client: str = "app",
    persona: str | None = None,
    coach: dict[str, Any] | None = None,
    coach_raw: str | None = None,
    cli_meta: dict[str, Any] | None = None,
    skip_reason: str | None = None,
    run_id: str | None = None,
    compile_semantics: str | None = None,
    test: bool | None = None,
    allow_draft_override: bool | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Append one immutable distill record; returns the row written."""
    resp_hash = fable_response_hash(coach_raw if coach is not None or coach_raw else None)
    record_id = compute_record_id(node_id=node_id, compile_ts=compile_ts, fable_response_hash=resp_hash)
    row: dict[str, Any] = {
        "record_id": record_id,
        "compile_ts": compile_ts,
        "node_id": node_id,
        "task": task,
        "client": client,
        "instruction": instruction,
        "student_draft": student_draft,
        "coach": coach,
        "coach_raw": coach_raw,
        "cli_meta": cli_meta,
        "skip_reason": skip_reason,
        "fable_response_hash": resp_hash,
        "run_id": run_id,
    }
    if persona:
        row["persona"] = persona
    if compile_semantics:
        row["compile_semantics"] = compile_semantics
    if test is True:
        row["test"] = True
    if allow_draft_override:
        row["allow_draft_override"] = True
    append_jsonl(path or RECORDS_PATH, row)
    return row
