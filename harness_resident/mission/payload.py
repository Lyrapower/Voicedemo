"""Compressed logic package for one mission hop (Grid 9-08 shape).

payload = {action, bounds, resources, prior}
  action    = the one thing this hop does
  bounds    = {read_only, budget_remaining, stop_conditions, forbidden}
  resources = {worker, data_sources, egress_lane, sandbox_mounts}
  prior     = {event_id, status, worker_output_tail, error} | None  (first hop = None)

Worker is assumed memoryless: prior must carry the previous error code; the worker
must not guess a missing prior. validate_payload rejects a package missing any of
action/bounds/resources so the runner never submits a malformed hop.
"""
from __future__ import annotations

import re
from typing import Any

JOB_BLOCK_RE = re.compile(r"```job\s*\n(.*?)```", re.S)
STOP_RE = re.compile(r"```STOP\b(.*?)```", re.S)


def prior_from_receipt(event_id: str, status: str, worker_output: str, error: str = "") -> dict[str, Any]:
    tail = (worker_output or "")[-2000:]
    return {"event_id": event_id, "status": status, "worker_output_tail": tail, "error": error}


def build_payload(*, action: str, bounds: dict, resources: dict, prior: dict | None) -> dict[str, Any]:
    return {"action": action, "bounds": bounds, "resources": resources, "prior": prior}


def validate_payload(payload: dict | None) -> tuple[bool, str]:
    """Return (ok, reason). ok=False if action/bounds/resources missing."""
    if not isinstance(payload, dict):
        return False, "payload not a dict"
    if not payload.get("action"):
        return False, "missing action"
    for key in ("bounds", "resources"):
        if key not in payload or payload[key] is None:
            return False, f"missing {key}"
        if not isinstance(payload[key], dict):
            return False, f"{key} must be a dict"
    return True, ""


def parse_next_block(text: str) -> dict | None:
    """Extract the first ```job block from worker output. Returns parsed dict or None."""
    if not text:
        return None
    m = JOB_BLOCK_RE.search(text)
    if not m:
        return None
    body = m.group(1).strip()
    # parse key: value lines into a flat dict (same shape H1 uses)
    out: dict[str, Any] = {}
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" in s:
            k, v = s.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    if not out:
        return None
    return out


def is_stop(text: str) -> bool:
    if not text:
        return False
    return bool(STOP_RE.search(text)) or "STOP" in (text or "").strip().splitlines()[-1:][0].upper()[:6]


def lineage_summary(hops: list[dict], limit: int = 20) -> str:
    """One line per hop: action/status/one-line conclusion. <= limit hops."""
    lines = []
    for h in hops[-limit:]:
        n = h.get("hop")
        st = h.get("status", "")
        concl = (h.get("conclusion") or "")[:140]
        lines.append(f"hop {n}: status={st} — {concl}")
    return "\n".join(lines) if lines else "(none)"
