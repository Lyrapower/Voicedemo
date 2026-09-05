"""Provenance event log — append-only JSONL. (Fable review 2026-08-26, fills Acceptance B/E and CURSOR item 5)

collaboration.build_collaboration_view() consumes events, but nothing in the bundle emitted any.
Every ActionEnvelope and FactualReceipt passes through here; the collaboration view is derived from this file only.
VERIFIED is a verifier-issued status: `mark_verified()` is the sole writer of status="VERIFIED" and it requires a
deterministic predicate result — a model, a tool, or a caller cannot construct a VERIFIED receipt (bundle probe:
FactualReceipt(status="VERIFIED") was accepted from any caller).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from dataclasses import asdict
from typing import Any, Callable, Iterable

from app.harness.action_envelope import ActionEnvelope, FactualReceipt

LOG_PATH_ENV = "HARNESS_PROVENANCE_LOG"
_RECORDING = False

# §八 证据等级梯(契约 v1.3):index 越小 = 等级越高(越可信)。"只降不升" = 新 receipt 的 index 不得小于同 action 前序 receipt 的 index。
GRADE_ORDER: dict[str, int] = {
    "attested": 0,
    "witnesses_agree": 1,
    "witness_only": 2,
    "issuer_claim": 3,
    "secondhand": 4,
    "unverified": 5,
}


def _path() -> str:
    return os.getenv(LOG_PATH_ENV, os.path.join("state", "provenance.jsonl"))


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _write(event: dict[str, Any]) -> dict[str, Any]:
    p = _path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    prev = ""
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size:
                f.seek(max(0, size - 4096))
                tail = f.read().decode("utf-8", errors="ignore").strip().splitlines()
                if tail:
                    prev = json.loads(tail[-1]).get("event_hash", "")
    except FileNotFoundError:
        pass
    body = dict(event)
    body["prev_hash"] = prev
    body["event_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(body, ensure_ascii=False) + "\n")
    return body


def record_action(envelope: ActionEnvelope) -> dict[str, Any]:
    global _RECORDING
    envelope.validate()
    d = asdict(envelope)
    _RECORDING = True
    try:
        return _write({"ts": _now(), "kind": "action", "mission_id": d["mission_id"], "event_id": d["action_id"],
                       "actor": d["decision_origin"], "action": d["operation"], "target": d["selected_resource"],
                       "authorization_scope": d["authorization_scope"], "arguments": d.get("arguments") or {}})
    finally:
        _RECORDING = False


def _enforce_monotone_descent(mission_id: str, action_id: str, grade: str, is_reconcile: bool) -> None:
    """§八 只降不升:同一 (mission_id, action_id) 的 receipt 等级只能往 unverified 方向降,不能升。
    处决案②一般 receipt:ascending(新 index < 旧 index)→ 拒;相同允许。
    处决案③对账层 receipt(metadata.reconcile=True):≥ 原级(新 index <= 旧 index,即相同或升)→ 拒;只能严格降。"""
    new_idx = GRADE_ORDER[grade]
    for e in read_events(mission_id):
        if e.get("kind") != "receipt" or e.get("event_id") != action_id:
            continue
        prior = e.get("evidence_grade")
        if not prior or prior not in GRADE_ORDER:
            continue
        prior_idx = GRADE_ORDER[prior]
        if is_reconcile:
            if new_idx <= prior_idx:
                raise ValueError(
                    f"对账层等级只能严格降(§八 ③):prior={prior}(idx {prior_idx}) new={grade}(idx {new_idx})"
                )
        else:
            if new_idx < prior_idx:
                raise ValueError(
                    f"证据等级只降不升(§八 ②):prior={prior}(idx {prior_idx}) new={grade}(idx {new_idx})"
                )


def record_receipt(receipt: FactualReceipt) -> dict[str, Any]:
    global _RECORDING
    if receipt.status == "VERIFIED" and not (receipt.metadata or {}).get("verifier_predicate"):
        raise ValueError("VERIFIED receipts may only be produced by mark_verified()")
    meta = receipt.metadata or {}
    grade = meta.get("evidence_grade")
    if grade and grade in GRADE_ORDER:
        _enforce_monotone_descent(receipt.mission_id, receipt.action_id, grade, bool(meta.get("reconcile")))
        derived = meta.get("derived_from")
        if isinstance(derived, dict):
            parent_grade = derived.get("evidence_grade")
            if parent_grade in GRADE_ORDER and GRADE_ORDER[grade] < GRADE_ORDER[parent_grade]:
                raise ValueError(
                    f"derived fact exceeds parent grade: child={grade} parent={parent_grade}"
                )
    _RECORDING = True
    try:
        d = receipt.to_dict()
    finally:
        _RECORDING = False
    ev = {"ts": _now(), "kind": "receipt", "mission_id": d["mission_id"], "event_id": d["action_id"],
          "actor": "TOOL" if d["executed"] else "HARNESS", "action": "receipt", "target": "",
          "status": d["status"], "evidence_pointer": d.get("evidence_pointer") or "",
          "receipt_hash": d.get("receipt_hash") or hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16],
          "metadata": d.get("metadata") or {}}
    if grade and grade in GRADE_ORDER:
        ev["evidence_grade"] = grade
    return _write(ev)


def mark_verified(receipt: FactualReceipt, predicate: Callable[[FactualReceipt], bool], predicate_name: str) -> FactualReceipt:
    """The only path to VERIFIED: a named deterministic predicate over the receipt returns True."""
    ok = bool(predicate(receipt))
    meta = dict(receipt.metadata or {})
    meta["verifier_predicate"] = predicate_name
    meta["verifier_result"] = ok
    out = FactualReceipt(**{**receipt.__dict__, "status": "VERIFIED" if ok else "FAILED_VERIFICATION", "metadata": meta})
    _write({"ts": _now(), "kind": "verify", "mission_id": out.mission_id, "event_id": out.action_id, "actor": "VERIFIER",
            "action": predicate_name, "target": "", "status": out.status})
    return out


def read_events(mission_id: str | None = None) -> list[dict[str, Any]]:
    p = _path()
    if not os.path.exists(p):
        return []
    out = []
    for line in open(p, encoding="utf-8"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if mission_id is None or e.get("mission_id") == mission_id:
            out.append(e)
    return out


def verify_chain(events: Iterable[dict[str, Any]]) -> bool:
    prev = ""
    for e in events:
        body = {k: v for k, v in e.items() if k != "event_hash"}
        if body.get("prev_hash", "") != prev:
            return False
        h = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        if h != e.get("event_hash"):
            return False
        prev = e["event_hash"]
    return True
