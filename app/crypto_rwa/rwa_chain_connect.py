"""RWA chain connect · one adapter: gate → reader → FactualReceipt → provenance → publish.

Does not invent addresses or fill failed reads with zero supply/NAV.
Does not mint USER/GRID_LOCAL; caller must pass an authenticated context.
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.harness.action_envelope import ActionEnvelope, FactualReceipt, VALID_RECEIPT_STATUS
from app.harness import provenance
from app.harness.resource_gate import gate
from app.crypto_rwa import rwa_onchain_reader as R

ROOT = Path(__file__).resolve().parents[2]
RESOURCE = "crypto.rwa.scan_public"
MONEY_OPS = frozenset({"transfer", "send", "approve", "swap", "trade", "withdraw"})

# Lyra-authorized RPC vendors only (溯补 3). Host suffix match; never log full URL.
AUTHORIZED_VENDORS = {
    "alchemy": ("alchemy.com",),
    "quicknode": ("quiknode.pro", "quicknode.com"),
    "ankr": ("ankr.com",),
}

GRADE_ORDER = R.GRADE_ORDER


def _state_dir() -> Path:
    return Path(os.environ.get("RWA_CONNECT_STATE", str(ROOT / "state")))


def published_path() -> Path:
    return Path(os.environ.get("RWA_CONNECT_PUBLISHED", str(_state_dir() / "rwa_onchain_published.json")))


def lock_path() -> Path:
    return Path(os.environ.get("RWA_CONNECT_LOCK", str(_state_dir() / "rwa_connect.lock")))


def evidence_dir() -> Path:
    return Path(os.environ.get("RWA_CONNECT_EVIDENCE", str(ROOT / "deliver" / "crypto" / "evidence" / "onchain")))


def _ensure_ssl_cert_file() -> None:
    """Python.org 3.13 on this Mac ships cafile=None; use certifi without disabling verify."""
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except Exception:
        pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def vendor_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for name, suffixes in AUTHORIZED_VENDORS.items():
        if any(host == s or host.endswith("." + s) for s in suffixes):
            return name
    raise ValueError("RPC endpoint not on authorized list (Alchemy/QuickNode/Ankr)")


def node_ownership_of(url: str) -> str:
    vendor_of(url)
    return "third_party"


def _evidence_pointer(ev_path: Path) -> str:
    try:
        return str(ev_path.relative_to(ROOT))
    except ValueError:
        return str(ev_path)


def worse_grade(a: str, b: str) -> str:
    ia, ib = GRADE_ORDER.get(a, 5), GRADE_ORDER.get(b, 5)
    return a if ia >= ib else b


def grade_fact(
    *,
    confidence: str,
    node_ownership: str,
    same_block: bool,
    independent_upstreams: bool,
    attested_proof: bool,
    shared_upstream: bool = False,
    timeout: bool = False,
) -> str:
    """Deterministic §八 adapter. third_party never attested (溯补 2). dual ≠ attested."""
    if timeout or confidence == "unverified":
        raw = "unverified"
    elif not same_block:
        raw = "unverified"
    elif shared_upstream or not independent_upstreams:
        raw = "witness_only" if confidence in ("dual", "single") else "unverified"
    elif confidence == "dual" and independent_upstreams:
        raw = "witnesses_agree"
    elif confidence == "single":
        raw = "witness_only"
    else:
        raw = "unverified"

    if node_ownership == "self_hosted" and attested_proof and raw == "witnesses_agree":
        return "attested"
    if GRADE_ORDER.get(raw, 5) < GRADE_ORDER["witnesses_agree"]:
        return "witnesses_agree"
    return raw


def _require_context(context: dict[str, Any]) -> dict[str, str]:
    need = ("mission_id", "action_id", "decision_origin")
    missing = [k for k in need if not context.get(k)]
    if missing:
        raise ValueError("context missing %s; reader cannot fill actor" % ",".join(missing))
    if context["decision_origin"] in ("HARNESS", "VERIFIER", "TOOL"):
        raise ValueError("decision_origin cannot be HARNESS/VERIFIER/TOOL")
    return {k: str(context[k]) for k in need}


def action_id_for(run_id: str, symbol: str, chain: str) -> str:
    return f"{run_id}|{symbol}|{chain}"


def _lock():
    p = lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = open(p, "a+")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    return fh


def load_published() -> dict[str, Any]:
    p = published_path()
    if not p.exists():
        return {"status": "empty", "receipts": [], "asof": None, "stale": True, "connected": False}
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["stale"] = True
    return doc


def _reuse_from_log(mission_id: str, aid: str) -> dict[str, Any] | None:
    for e in reversed(provenance.read_events(mission_id)):
        if e.get("kind") == "receipt" and e.get("event_id") == aid:
            payload: dict[str, Any] = {}
            ptr = e.get("evidence_pointer") or ""
            evp = Path(ptr)
            if not evp.is_absolute():
                evp = ROOT / ptr
            if evp.exists():
                try:
                    payload = json.loads(evp.read_text(encoding="utf-8"))
                except Exception:
                    payload = {}
            meta = e.get("metadata") or {}
            return {
                "receipt_id": e.get("event_hash"),
                "status": e.get("status"),
                "factual_payload": payload,
                "symbol": meta.get("symbol") or payload.get("symbol"),
                "chain": meta.get("chain") or payload.get("chain"),
                "run_id": meta.get("run_id"),
                "event_id": aid,
                "evidence_grade": e.get("evidence_grade") or meta.get("evidence_grade"),
                "observed_at": payload.get("observed_at"),
                "chain_link": e.get("prev_hash"),
                "reused": True,
            }
    return None


def _strip_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(s in kl for s in ("rpc", "api_key", "secret", "token", "authorization", "rpc_url")):
                continue
            out[k] = _strip_secrets(v)
        return out
    if isinstance(obj, list):
        return [_strip_secrets(x) for x in obj]
    if isinstance(obj, str) and obj.startswith("http") and any(v in obj.lower() for v in ("alchemy", "quiknode", "ankr")):
        return "[redacted-rpc]"
    return obj


def read_with_receipt(
    context: dict[str, Any],
    registry_entry: dict[str, Any],
    *,
    run_id: str,
    card: dict[str, Any] | None = None,
    rpc_pair: tuple[str | None, str | None] | None = None,
    policy: str = "required",
    attested_proof: bool = False,
    derived_from: dict[str, Any] | None = None,
    same_block: bool | None = None,
    independent_upstreams: bool | None = None,
    shared_upstream: bool | None = None,
    timeout: bool = False,
    fail_record: bool = False,
) -> dict[str, Any]:
    """Gate → reader card → one FactualReceipt on the existing provenance chain."""
    _ensure_ssl_cert_file()
    ctx = _require_context(context)
    symbol = str(registry_entry.get("symbol") or "?")
    chain = str(registry_entry.get("chain") or "?")
    aid = ctx["action_id"] if "|" in str(ctx["action_id"]) else action_id_for(run_id, symbol, chain)
    reused = _reuse_from_log(ctx["mission_id"], aid)
    if reused and not fail_record:
        return reused

    op = str(context.get("operation") or "rwa.onchain_read")
    if any(x in op.lower() for x in MONEY_OPS):
        raise ValueError("money-moving methods are forbidden on this path")

    env = ActionEnvelope(
        mission_id=ctx["mission_id"],
        action_id=aid,
        decision_origin=ctx["decision_origin"],
        selected_resource=RESOURCE,
        operation=op,
        arguments={"symbol": symbol, "chain": chain, "run_id": run_id},
        authorization_scope="read_only",
        expected_effect="read-only eth_call; no funds move",
        timestamp=_now(),
    )
    decision = gate(env)
    if not decision.allowed:
        last = _reuse_from_log(ctx["mission_id"], aid)
        return last or {
            "receipt_id": None,
            "status": "DENIED",
            "factual_payload": {"error": decision.reason, "symbol": symbol, "chain": chain},
            "symbol": symbol, "chain": chain, "run_id": run_id,
        }

    ownership = "third_party"
    vendors: list[str] = []
    if rpc_pair:
        for u in rpc_pair:
            if not u:
                continue
            vendors.append(vendor_of(u))
            ownership = node_ownership_of(u)

    if card is None:
        if not registry_entry.get("address"):
            card = {
                "symbol": symbol, "chain": chain, "address": None,
                "error": "注册表无地址(待官方文档核实),拒读不猜",
                "confidence": "unverified", "supply_units": None, "nav_usd": None,
                "total_supply": None, "decimals": None,
            }
        else:
            url, url2 = (rpc_pair or (None, None))
            if not url:
                card = {
                    "symbol": symbol, "chain": chain,
                    "error": "RPC 未设", "confidence": "unverified",
                    "supply_units": None, "nav_usd": None, "total_supply": None,
                }
            else:
                card = R.read_token(url, registry_entry, "latest", url2, policy)

    if same_block is None:
        same_block = True
    if independent_upstreams is None:
        independent_upstreams = len(set(vendors)) >= 2
    if shared_upstream is None:
        shared_upstream = bool(vendors) and len(set(vendors)) < 2 and bool(rpc_pair and rpc_pair[0] and rpc_pair[1])

    timeout = timeout or "timeout" in str(card.get("error") or "").lower()
    grade = grade_fact(
        confidence=str(card.get("confidence") or "unverified"),
        node_ownership=ownership,
        same_block=bool(same_block),
        independent_upstreams=bool(independent_upstreams) and not shared_upstream,
        attested_proof=attested_proof,
        shared_upstream=bool(shared_upstream),
        timeout=timeout,
    )

    status = "FAILED" if (card.get("error") and card.get("supply_units") is None) else "EXECUTED"
    if timeout:
        status = "TIMEOUT"
    if status not in VALID_RECEIPT_STATUS:
        status = "FAILED"

    payload = _strip_secrets({
        "symbol": symbol,
        "chain": chain,
        "chain_id": registry_entry.get("chain_id"),
        "address": registry_entry.get("address"),
        "method": "eth_call totalSupply/symbol/decimals",
        "block": card.get("block"),
        "observed_at": card.get("read_ts") or _now(),
        "supply_units": card.get("supply_units"),
        "total_supply": card.get("total_supply"),
        "decimals": card.get("decimals"),
        "nav_usd": card.get("nav_usd"),
        "nav_source": card.get("nav_source"),
        "supply_grade": grade,
        "nav_grade": worse_grade(grade, "witness_only") if (card.get("nav_source") or {}).get("status") == "cross_chain" else grade,
        "issuer_grade": "issuer_claim",
        "confidence": card.get("confidence"),
        "error": card.get("error"),
        "note": card.get("note"),
        "node_ownership": ownership,
        "vendors": vendors,
        "run_id": run_id,
    })
    if payload.get("error") and payload.get("supply_units") is None:
        payload["total_supply"] = None
        payload["nav_usd"] = None

    ev_dir = evidence_dir()
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_path = ev_dir / f"rwa-connect-{run_id}-{symbol}-{chain}.json"
    ev_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    meta: dict[str, Any] = {
        "evidence_grade": grade,
        "run_id": run_id,
        "symbol": symbol,
        "chain": chain,
        "node_ownership": ownership,
        "reader": "rwa_chain_connect",
    }
    if derived_from:
        meta["derived_from"] = derived_from

    if fail_record:
        raise RuntimeError("injected write-chain failure")

    receipt = FactualReceipt(
        mission_id=ctx["mission_id"],
        action_id=aid,
        status=status,
        executed=status == "EXECUTED",
        result=payload,
        error=str(payload.get("error") or ""),
        evidence_pointer=_evidence_pointer(ev_path),
        observed_value={"supply_units": payload.get("supply_units"), "nav_usd": payload.get("nav_usd")},
        metadata=meta,
    )
    ev = provenance.record_receipt(receipt)
    return {
        "receipt_id": ev.get("event_hash"),
        "status": status,
        "factual_payload": payload,
        "symbol": symbol,
        "chain": chain,
        "run_id": run_id,
        "event_id": aid,
        "evidence_grade": grade,
        "observed_at": payload.get("observed_at"),
        "chain_link": ev.get("prev_hash"),
        "reused": False,
    }


def _write_published(doc: dict[str, Any]) -> None:
    p = published_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def connect_run(
    context: dict[str, Any],
    *,
    run_id: str | None = None,
    registry: list | None = None,
    rpc_env: dict | None = None,
    attested_proof: bool = False,
    fail_publish: bool = False,
) -> dict[str, Any]:
    _ensure_ssl_cert_file()
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    registry = list(registry or R.DEFAULT_REGISTRY)
    if rpc_env is None:
        rpc_env = {}
        for cid, pre in R.CHAINS.items():
            u1, u2 = os.getenv(pre + "_RPC_URL"), os.getenv(pre + "_RPC_URL_2")
            pol = (os.getenv(pre + "_RPC_SECOND_POLICY") or ("optional" if pre == "BSC" else "required")).lower()
            if u1:
                vendor_of(u1)
                if u2:
                    vendor_of(u2)
                rpc_env[cid] = (u1, u2 or None, pol)
    fh = _lock()
    try:
        rows: list[dict[str, Any]] = []
        write_fail = False
        try:
            doc = R.run(None, registry, None, None, rpc_env, emit_provenance=False)
        except Exception as exc:
            write_fail = True
            doc = {"cards": [], "skipped": [{"reason": str(exc)[:160]}], "summary": {}, "read_ts": _now()}
        cards = {(c.get("symbol"), c.get("chain")): c for c in doc.get("cards") or []}
        for e in registry:
            pair = rpc_env.get(e.get("chain_id"))
            rpc_pair = (pair[0], pair[1]) if pair else (None, None)
            pol = pair[2] if pair and len(pair) > 2 else "required"
            card = cards.get((e.get("symbol"), e.get("chain")))
            ctx = dict(context)
            ctx["action_id"] = action_id_for(run_id, e["symbol"], e.get("chain") or "?")
            try:
                row = read_with_receipt(
                    ctx, e, run_id=run_id, card=card, rpc_pair=rpc_pair,
                    policy=pol, attested_proof=attested_proof,
                )
            except Exception as exc:
                write_fail = True
                row = {
                    "receipt_id": None, "status": "FAILED",
                    "factual_payload": {"error": str(exc)[:200], "symbol": e.get("symbol"), "chain": e.get("chain")},
                    "symbol": e.get("symbol"), "chain": e.get("chain"), "run_id": run_id,
                }
            rows.append(row)
        any_id = any(r.get("receipt_id") for r in rows)
        published = {
            "kind": "rwa_onchain_published",
            "run_id": run_id,
            "asof": doc.get("read_ts") or _now(),
            "connected": bool(any_id and not write_fail and not fail_publish),
            "receipts": rows,
            "summary": _strip_secrets(doc.get("summary") or {}),
            "stale_label": "last_success",
            "last_success_asof": None,
            "last_success_receipt_id": None,
        }
        prev = load_published()
        if prev.get("connected") and prev.get("asof"):
            published["last_success_asof"] = prev.get("asof")
            ok = next((r for r in (prev.get("receipts") or []) if r.get("receipt_id") and r.get("status") == "EXECUTED"), {})
            published["last_success_receipt_id"] = ok.get("receipt_id")
        if fail_publish or (write_fail and not any_id):
            published["connected"] = False
            published["error"] = "write-chain or publish failed; not marked connected"
            if fail_publish:
                return published
        _write_published(published)
        return published
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
