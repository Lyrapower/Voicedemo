"""Full Grid chain verification gate — required before Aster SP / FIELD_NOW injection."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

GATEWAY_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = GATEWAY_DIR.parent
SCRIPTS = PROJECT_ROOT / "scripts"
REPLAY_PATH = PROJECT_ROOT / ".grid_cleanroom" / "verification_replay.json"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

GRID_CHAIN_SCHEMA_VERSION = "grid-chain-v1"
ALLOWED_SIGNER_IDS = frozenset({
    "keyholder-v1",
    "grid-trace-v1",
    "grid-scheduler-v1",
    "alpha-factory-v1",
})

SERVICE_SIGNER_KEY_ENV = {
    "keyholder-v1": "GRID_KEYHOLDER_KEY",
    "grid-scheduler-v1": "GRID_SCHEDULER_SIGNER_KEY",
    "alpha-factory-v1": "GRID_FACTORY_SIGNER_KEY",
}

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)

_replay_lock = threading.Lock()


@dataclass
class GridChainVerification:
    ok: bool
    reason: str | None = None
    missing_layers: list[str] = field(default_factory=list)
    route_id: str | None = None
    signer_id: str | None = None
    schema_version: str | None = None
    keyholder_verdict: str | None = None
    trace_id: str | None = None
    payload_hash: str | None = None

    def to_error_dict(self) -> dict[str, Any]:
        return {
            "type": "grid_chain_verification_required",
            "reason": self.reason or "grid chain verification failed",
            "missing_layers": self.missing_layers,
            "schema_version": self.schema_version,
            "route_id": self.route_id,
            "signer_id": self.signer_id,
            "keyholder_verdict": self.keyholder_verdict,
            "trace_id": self.trace_id,
            "payload_hash": self.payload_hash,
        }


class GridVerificationRequired(Exception):
    def __init__(self, result: GridChainVerification) -> None:
        self.result = result
        super().__init__(result.reason or "grid chain verification required")


def normalize_messages_for_hash(messages: Any) -> list[dict[str, Any]]:
    """Coerce message content for stable payload_hash (missing/null → \"\")."""
    if not isinstance(messages, list):
        return []
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if content is None:
            norm_content: Any = ""
        elif isinstance(content, (str, list)):
            norm_content = content
        else:
            norm_content = str(content)
        out.append({"role": m.get("role"), "content": norm_content})
    return out


def canonical_payload_hash(body: dict[str, Any]) -> str:
    subset = {
        "model": body.get("model"),
        "messages": normalize_messages_for_hash(body.get("messages")),
    }
    canonical = json.dumps(subset, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_replay() -> dict[str, Any]:
    if not REPLAY_PATH.is_file():
        return {"routes": {}, "updated_at": 0.0}
    try:
        return json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"routes": {}, "updated_at": 0.0}


def _save_replay(data: dict[str, Any]) -> None:
    REPLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPLAY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def register_route_id(route_id: str, *, stage: str = "pending") -> bool:
    """Register route_id at trace-seal; returns False if replay."""
    now = time.time()
    with _replay_lock:
        data = _load_replay()
        routes: dict[str, Any] = data.setdefault("routes", {})
        # prune > 24h
        for rid, meta in list(routes.items()):
            if now - float(meta.get("ts", 0)) > 86400:
                del routes[rid]
        if route_id in routes:
            return False
        routes[route_id] = {"ts": now, "stage": stage}
        data["updated_at"] = now
        _save_replay(data)
    return True


def _consume_route_id(route_id: str, *, stage: str = "chat") -> bool:
    now = time.time()
    with _replay_lock:
        data = _load_replay()
        routes: dict[str, Any] = data.setdefault("routes", {})
        meta = routes.get(route_id)
        if not meta:
            return False
        if meta.get("stage") == "consumed":
            return False
        meta["stage"] = stage
        meta["consumed_at"] = now
        data["updated_at"] = now
        _save_replay(data)
    return True


def _signer_key_path(signer_id: str) -> Path:
    env = SERVICE_SIGNER_KEY_ENV.get(signer_id, "GRID_KEYHOLDER_KEY")
    custom = os.environ.get(env, "").strip()
    if custom:
        return Path(custom)
    return PROJECT_ROOT / ".grid_cleanroom" / "keyholder.key"


def verify_keyholder_for_signer(
    signer_id: str,
    nonce: str,
    ts: float,
    response: str,
    *,
    ttl: int = 90,
) -> dict[str, Any]:
    import keyholder_challenge as kh

    key_path = _signer_key_path(signer_id)
    if not key_path.is_file():
        return {
            "verified": False,
            "verdict": "ERROR",
            "reason": f"signer key missing for {signer_id}: {key_path}",
        }
    key = key_path.read_bytes().strip()
    log = kh._load_challenge_log()
    reason = None
    verdict = "GRID_ABSENT"
    if nonce in log.get("used_nonces", []):
        reason = "nonce already used (replay rejected)"
    elif (kh.now() - ts) > ttl:
        reason = f"challenge expired (older than {ttl}s)"
    elif (kh.now() - ts) < -5:
        reason = "challenge timestamp is in the future"
    else:
        expected = kh.compute_response(nonce, ts, key)
        if __import__("hmac").compare_digest(expected, response or ""):
            verdict = "VERIFIED_KEYHOLDER"
        else:
            reason = "response does not match expected keyholder signature"
    log.setdefault("used_nonces", []).append(nonce)
    log.setdefault("history", []).append({
        "at": kh.iso(kh.now()), "nonce": nonce, "verdict": verdict, "reason": reason, "signer_id": signer_id,
    })
    kh._save_challenge_log(log)
    return {"verdict": verdict, "verified": verdict == "VERIFIED_KEYHOLDER", "reason": reason}


def _bundle(body: dict[str, Any]) -> dict[str, Any] | None:
    raw = body.get("grid_verification")
    return raw if isinstance(raw, dict) else None


def _verify_trace_hmac(trace: dict[str, Any]) -> tuple[bool, str]:
    try:
        import cleanroom as _cr
    except Exception as exc:
        return False, f"cleanroom unavailable: {exc}"
    try:
        ok, msg = _cr.verify_trace(trace)
        return ok, msg
    except Exception as exc:
        return False, str(exc)


def require_full_grid_verification(
    body: dict[str, Any],
    *,
    kh_verify: Callable[..., dict[str, Any]] | None = None,
    kh_ttl: int = 90,
) -> GridChainVerification:
    bundle = _bundle(body)
    if not bundle:
        return GridChainVerification(
            ok=False,
            reason="grid_verification bundle required for demo/aster",
            missing_layers=["schema", "route", "signer", "keyholder", "hmac", "payload_hash"],
        )

    missing: list[str] = []

    schema = str(bundle.get("schema_version") or "").strip()
    if schema != GRID_CHAIN_SCHEMA_VERSION:
        missing.append("schema")

    route_id = str(bundle.get("route_id") or "").strip()
    if not _UUID_RE.match(route_id):
        missing.append("route")

    signer_id = str(bundle.get("signer_id") or "").strip()
    if signer_id not in ALLOWED_SIGNER_IDS:
        missing.append("signer")

    payload_hash = str(bundle.get("payload_hash") or "").strip()
    if not payload_hash or len(payload_hash) != 64:
        missing.append("payload_hash")
    else:
        expected_ph = canonical_payload_hash(body)
        if payload_hash != expected_ph:
            return GridChainVerification(
                ok=False,
                reason="payload_hash mismatch",
                missing_layers=["payload_hash"],
                route_id=route_id or None,
                signer_id=signer_id or None,
                schema_version=schema or None,
                payload_hash=payload_hash,
            )

    keyholder_verdict = None
    kh = bundle.get("keyholder")
    if not isinstance(kh, dict):
        missing.append("keyholder")
    else:
        nonce = kh.get("nonce")
        ts = kh.get("ts")
        response = kh.get("response")
        if not (nonce and ts is not None and response is not None):
            missing.append("keyholder")
        elif not signer_id:
            missing.append("keyholder")
        else:
            kh_result = verify_keyholder_for_signer(
                signer_id, str(nonce), float(ts), str(response), ttl=kh_ttl,
            )
            keyholder_verdict = str(kh_result.get("verdict") or "GRID_ABSENT")
            if not kh_result.get("verified"):
                return GridChainVerification(
                    ok=False,
                    reason=kh_result.get("reason") or "keyholder verification failed",
                    missing_layers=["keyholder"],
                    route_id=route_id or None,
                    signer_id=signer_id or None,
                    schema_version=schema or None,
                    keyholder_verdict=keyholder_verdict,
                    payload_hash=payload_hash or None,
                )

    trace = bundle.get("trace")
    trace_id = None
    if not isinstance(trace, dict):
        missing.append("hmac")
    else:
        trace_id = str(trace.get("trace_id") or "") or None
        hmac_ok, hmac_msg = _verify_trace_hmac(trace)
        if not hmac_ok:
            return GridChainVerification(
                ok=False,
                reason=f"trace HMAC failed: {hmac_msg}",
                missing_layers=["hmac"],
                route_id=route_id or None,
                signer_id=signer_id or None,
                schema_version=schema or None,
                keyholder_verdict=keyholder_verdict,
                trace_id=trace_id,
                payload_hash=payload_hash or None,
            )

    if missing:
        return GridChainVerification(
            ok=False,
            reason=f"missing or invalid layers: {', '.join(missing)}",
            missing_layers=missing,
            route_id=route_id or None,
            signer_id=signer_id or None,
            schema_version=schema or None,
            keyholder_verdict=keyholder_verdict,
            trace_id=trace_id,
            payload_hash=payload_hash or None,
        )

    if not _consume_route_id(route_id, stage="chat-consumed"):
        return GridChainVerification(
            ok=False,
            reason="route_id replay rejected (unknown or already consumed)",
            missing_layers=["route"],
            route_id=route_id,
            signer_id=signer_id,
            schema_version=schema,
            keyholder_verdict=keyholder_verdict,
            trace_id=trace_id,
            payload_hash=payload_hash,
        )

    return GridChainVerification(
        ok=True,
        route_id=route_id,
        signer_id=signer_id,
        schema_version=schema,
        keyholder_verdict=keyholder_verdict,
        trace_id=trace_id,
        payload_hash=payload_hash,
    )


def assert_chain_verified_for_aster(body: dict[str, Any], *, kh_verify: Callable[..., dict] | None = None) -> GridChainVerification:
    result = require_full_grid_verification(body, kh_verify=kh_verify)
    if not result.ok:
        raise GridVerificationRequired(result)
    return result
