"""GRID_TOPOLOGY v4.5 helpers: scope tokens, latency clamp, receipt materialize."""
from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any

CORS_ORIGIN = "http://127.0.0.1:8501"
PAGE_GET_PREFIXES = ("/api/receipts", "/api/jobs/", "/health")


def _token(name: str) -> str:
    return (os.getenv(name) or "").strip()


def resolve_scope(supplied: str) -> str | None:
    """full | h1 | page | None(unauth when tokens required). Empty supplied + no tokens = full (v1.2)."""
    full = _token("GRID_HARNESS_TOKEN")
    h1 = _token("GRID_HARNESS_H1_TOKEN")
    page = _token("GRID_HARNESS_PAGE_TOKEN")
    if not full and not h1 and not page:
        return "full"
    if full and supplied == full:
        return "full"
    if h1 and supplied == h1:
        return "h1"
    if page and supplied == page:
        return "page"
    return None


def clamp_latency_ms(raw, *, cap_ms: int) -> int | None:
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < 1:
        n = 1
    if cap_ms > 0 and n > cap_ms:
        n = cap_ms
    return n


def provenance_path() -> Path:
    return Path(os.getenv("HARNESS_PROVENANCE_LOG") or "state/provenance.jsonl")


def iter_provenance() -> list[dict[str, Any]]:
    p = provenance_path()
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def provenance_line_raw(event_id: str) -> str:
    p = provenance_path()
    if not p.is_file():
        return ""
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event_id") == event_id:
            return line
    return ""


def duration_ms_for(job_id: str, receipt_event_id: str) -> int | None:
    action_ts = None
    receipt_ts = None
    for ev in iter_provenance():
        if ev.get("mission_id") != job_id:
            continue
        if ev.get("kind") == "action" and action_ts is None:
            action_ts = ev.get("ts")
        if ev.get("event_id") == receipt_event_id and ev.get("kind") == "receipt":
            receipt_ts = ev.get("ts")
    if not action_ts or not receipt_ts:
        return None
    try:
        from datetime import datetime
        a = datetime.fromisoformat(str(action_ts).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(receipt_ts).replace("Z", "+00:00"))
        return max(0, int((b - a).total_seconds() * 1000))
    except (TypeError, ValueError):
        return None


def worker_output_from_events(events: list[dict[str, Any]]) -> str:
    for ev in reversed(events or []):
        if ev.get("kind") != "job_result":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, dict):
            for key in ("result", "text", "stdout"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    return val
            return json.dumps(payload, ensure_ascii=False)
        if isinstance(payload, str):
            return payload
    return ""


def record_grid_action(job: dict[str, Any]) -> dict[str, Any] | None:
    from app.harness.action_envelope import ActionEnvelope
    from app.harness import provenance
    jid = job["job_id"]
    env = ActionEnvelope(
        mission_id=jid,
        action_id=f"{jid}:job.run",
        decision_origin="GRID_LOCAL",
        selected_resource="harness.local_lane" if job.get("worker") == "local" else "harness.cc",
        operation="job.run",
        authorization_scope="read_only" if job.get("read_only") else "local_write",
        arguments={
            "worker": job.get("worker"),
            "kind": job.get("kind"),
            "origin": job.get("origin") or "",
            "context_hash": job.get("context_hash") or "",
        },
    )
    return provenance.record_action(env)


def record_tool_receipt(job: dict[str, Any], *, status: str, executed: bool, error: str = "") -> dict[str, Any]:
    from app.harness.action_envelope import FactualReceipt
    from app.harness.provenance import record_receipt
    jid = job["job_id"]
    ev = record_receipt(FactualReceipt(
        mission_id=jid,
        action_id=f"{jid}:run",
        status=status,
        executed=executed,
        error=error,
        metadata={
            "job_id": jid,
            "origin": job.get("origin") or "",
            "context_hash": job.get("context_hash") or "",
            "topology_ack": bool(job.get("topology_ack")),
            "executor": "tool",
            "route_id": "fs_tool",
            "route_class": "tool",
            "model_resolved": "",
        },
    ))
    return ev


def record_ack_receipt(job: dict[str, Any], *, status: str, executed: bool, error: str = "") -> dict[str, Any]:
    from app.harness.action_envelope import FactualReceipt
    from app.harness.provenance import record_receipt
    jid = job["job_id"]
    ev = record_receipt(FactualReceipt(
        mission_id=jid,
        action_id=f"{jid}:run",
        status=status,
        executed=executed,
        error=error,
        metadata={
            "job_id": jid,
            "origin": job.get("origin") or "",
            "context_hash": job.get("context_hash") or "",
            "topology_ack": bool(job.get("topology_ack")),
            "route_id": "topology_ack",
            "route_class": "ack",
            "model_resolved": "",
        },
    ))
    return ev


def last_nonempty_line(text: str) -> str:
    for line in reversed(str(text or "").splitlines()):
        if line.strip():
            return line
    return ""
