"""rwa.read — read-only wrap of app.crypto_rwa.rwa_onchain_reader.

rwa.xyz is GET-only reference (EGRESS lane=rwa). Numbers stay in
「rwa.xyz 参考值」; they are not copied onto supply/NAV dual fields.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.crypto_rwa.rwa_onchain_reader import (
    CHAINS,
    CONFIDENCE_TO_GRADE,
    DEFAULT_REGISTRY,
    GRADE_ORDER,
    rpc,
    run as reader_run,
)
from app.harness.action_envelope import FactualReceipt
from app.harness.provenance import record_receipt, read_events

PERM = "read_only"
EGRESS_PATH = str(Path(__file__).resolve().parents[2] / "EGRESS.md")
XYZ_ASSET = "https://app.rwa.xyz/assets/%s"
XYZ_COL = "rwa.xyz 参考值"
_MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
CONF_RANK = {
    "attested": 5,
    "witnesses_agree": 4,
    "witness_only": 3,
    "issuer_claim": 2,
    "secondhand": 1,
    "unverified": 0,
    "dispute": -1,
    "skipped": -2,
}


def _rpc_env_from_os() -> dict:
    out = {}
    for cid, pre in CHAINS.items():
        u1, u2 = os.getenv(pre + "_RPC_URL"), os.getenv(pre + "_RPC_URL_2")
        pol = (os.getenv(pre + "_RPC_SECOND_POLICY") or ("optional" if pre == "BSC" else "required")).lower()
        if u1:
            out[cid] = (u1, u2 or None, pol)
    return out


def _block_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v)
    try:
        return int(s, 16) if s.startswith("0x") else int(s)
    except ValueError:
        return None


def _probe_block(url: str) -> int | None:
    try:
        raw = rpc(url, "eth_blockNumber", [])
        return _block_int(raw)
    except Exception:
        return None


def _label_num(text: str, label: str) -> float | None:
    m = re.search(re.escape(label) + r"\s+\$?\s*([\d,.]+)\s*([KMBT])?", text, re.I)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suf = (m.group(2) or "").upper()
    if suf:
        n *= _MULT[suf]
    return n


def _label_int(text: str, label: str) -> int | None:
    m = re.search(re.escape(label) + r"\s+(\d[\d,]*)\b", text, re.I)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_rwa_xyz_text(text: str) -> dict:
    """Parse labeled marketplace fields. Missing labels → empty, no invented numbers."""
    out: dict[str, Any] = {"source": "rwa.xyz", "grade": "secondhand"}
    tav = _label_num(text, "Total Asset Value")
    nav = _label_num(text, "Net Asset Value")
    hol = _label_int(text, "Holders")
    if tav is not None:
        out["total_usd_all_chains"] = tav
    if nav is not None:
        out["nav_usd"] = nav
    if hol is not None:
        out["holders"] = hol
    if tav is None and nav is None and hol is None:
        out["status"] = "empty"
        out["reason"] = "no_labeled_fields"
    else:
        out["status"] = "ok"
    return out


def fetch_rwa_xyz_reference(symbol: str, *, opener=None, egress_path: str | None = None) -> dict:
    from harness.web_fetch_v3 import fetch
    url = XYZ_ASSET % str(symbol or "").upper()
    fr = fetch(url, "rwa", egress_path=egress_path or EGRESS_PATH, opener=opener, max_chars=16000)
    base = {"source": "rwa.xyz", "grade": "secondhand", "source_url": url, "http_status": fr.get("status")}
    if not fr.get("ok"):
        base.update(status="empty", reason=str(fr.get("reason") or fr.get("status") or "fetch_failed"))
        return base
    parsed = parse_rwa_xyz_text(fr.get("text") or "")
    parsed.update(source_url=fr.get("source_url") or url, http_status=fr.get("status"))
    return parsed


def _attach_xyz(card: dict, cache: dict, *, attach: bool, opener=None) -> None:
    if not attach:
        return
    sym = str(card.get("symbol") or "")
    if not sym:
        return
    if sym not in cache:
        cache[sym] = fetch_rwa_xyz_reference(sym, opener=opener)
    card[XYZ_COL] = dict(cache[sym])


def _strip_numbers(card: dict) -> dict:
    for k in ("total_supply", "supply_units", "supply_usd_at_par", "nav_usd", "supply_usd_at_nav"):
        card[k] = None
    return card


def _prior_card(symbol: str, chain: str) -> dict | None:
    last = None
    for ev in read_events():
        if ev.get("kind") != "receipt":
            continue
        meta = ev.get("metadata") or {}
        if meta.get("tool") != "rwa.read":
            continue
        if str(meta.get("symbol") or "") != symbol or str(meta.get("chain") or "") != chain:
            continue
        if ev.get("status") == "DENIED" and meta.get("reject") == "confidence_upgrade_without_newer_block":
            continue
        last = meta
    return last


def _g3_guard(card: dict) -> str | None:
    prior = _prior_card(card["symbol"], card["chain"])
    if not prior:
        return None
    new_rank = CONF_RANK.get(str(card.get("confidence") or ""), 0)
    old_rank = CONF_RANK.get(str(prior.get("confidence") or ""), 0)
    new_b = _block_int(card.get("block"))
    old_b = _block_int(prior.get("block"))
    if new_rank > old_rank and new_b is not None and old_b is not None and new_b < old_b:
        return "rejected:confidence_upgrade_without_newer_block"
    return None


def _emit(card: dict, *, status: str = "EXECUTED", error: str = "") -> dict:
    rec = FactualReceipt(
        mission_id="rwa-read",
        action_id="rwa.read:%s:%s:%s" % (card.get("symbol"), card.get("chain"), card.get("block")),
        status=status,
        executed=(status == "EXECUTED"),
        error=error,
        result={"confidence": card.get("confidence"), "block": card.get("block")},
        metadata={
            "tool": "rwa.read",
            "permission": PERM,
            "symbol": card.get("symbol"),
            "chain": card.get("chain"),
            "confidence": card.get("confidence"),
            "source_url": card.get("source_url"),
            "block": card.get("block"),
            "evidence_grade": card.get("evidence_grade") or card.get("confidence"),
            "reject": error.replace("rejected:", "") if error.startswith("rejected:") else "",
        },
    )
    return record_receipt(rec)


def execute(symbol: str | None = None, chain: str | None = None, *,
            registry: list | None = None, rpc_env: dict | None = None,
            attach_xyz: bool = True, xyz_opener=None) -> dict:
    """Input {symbol, chain} or empty (full registry). permission=read_only."""
    reg = list(registry if registry is not None else DEFAULT_REGISTRY)
    if symbol:
        reg = [e for e in reg if str(e.get("symbol") or "").upper() == symbol.upper()]
    if chain:
        reg = [e for e in reg if str(e.get("chain") or "").lower() == chain.lower()]
    env = dict(rpc_env if rpc_env is not None else _rpc_env_from_os())
    xyz_cache: dict = {}

    cards: list[dict] = []
    for e in reg:
        if not e.get("address"):
            card = {
                "symbol": e.get("symbol"), "chain": e.get("chain"), "address": None,
                "source_url": e.get("source_url"), "block": None,
                "confidence": "skipped", "evidence_grade": "skipped",
                "skip": "no_address", "total_supply": None, "supply_units": None,
                "nav_usd": None, "rpc_agree": None,
            }
            _attach_xyz(card, xyz_cache, attach=attach_xyz, opener=xyz_opener)
            _emit(card)
            cards.append(card)
            continue
        cid = e.get("chain_id")
        pair = env.get(cid)
        if not pair or not pair[0]:
            card = {
                "symbol": e.get("symbol"), "chain": e.get("chain"),
                "source_url": e.get("source_url"), "block": None,
                "confidence": "skipped", "evidence_grade": "skipped",
                "skip": "no_rpc", "total_supply": None,
            }
            _attach_xyz(card, xyz_cache, attach=attach_xyz, opener=xyz_opener)
            _emit(card)
            cards.append(card)
            continue
        url1, url2, pol = pair[0], (pair[1] if len(pair) > 1 else None), (pair[2] if len(pair) > 2 else "required")
        if url2:
            b1, b2 = _probe_block(url1), _probe_block(url2)
            if b1 is not None and b2 is not None and b1 != b2:
                card = {
                    "symbol": e.get("symbol"), "chain": e.get("chain"),
                    "source_url": e.get("source_url"), "block": b1,
                    "block_rpc2": b2, "confidence": "dispute", "evidence_grade": "dispute",
                    "rpc_agree": False, "total_supply": None, "supply_units": None, "nav_usd": None,
                }
                _strip_numbers(card)
                _attach_xyz(card, xyz_cache, attach=attach_xyz, opener=xyz_opener)
                _emit(card)
                cards.append(card)
                continue
        doc = reader_run(None, [e], None, None, {cid: (url1, url2, pol)}, emit_provenance=False)
        for raw in doc.get("cards") or []:
            card = dict(raw)
            grade = card.get("evidence_grade") or CONFIDENCE_TO_GRADE.get(card.get("confidence") or "", "unverified")
            if card.get("confidence") == "dual":
                card["confidence"] = "witnesses_agree"
                card["rpc_agree"] = True
            elif card.get("confidence") == "single":
                card["confidence"] = "witness_only"
            elif card.get("second_source", {}).get("match") is False:
                card["confidence"] = "dispute"
                _strip_numbers(card)
            else:
                card["confidence"] = grade if grade in CONF_RANK else "unverified"
            card["evidence_grade"] = card["confidence"]
            why = _g3_guard(card)
            if why:
                _attach_xyz(card, xyz_cache, attach=attach_xyz, opener=xyz_opener)
                _emit(card, status="DENIED", error=why)
                card["reject"] = why
                cards.append(card)
                continue
            _attach_xyz(card, xyz_cache, attach=attach_xyz, opener=xyz_opener)
            _emit(card)
            cards.append(card)
        for sk in doc.get("skipped") or []:
            card = {
                "symbol": sk.get("symbol") or e.get("symbol"),
                "chain": sk.get("chain") or e.get("chain"),
                "confidence": "skipped", "evidence_grade": "skipped",
                "skip": sk.get("reason"), "block": None,
            }
            _attach_xyz(card, xyz_cache, attach=attach_xyz, opener=xyz_opener)
            _emit(card)
            cards.append(card)
    return {"ok": True, "permission": PERM, "tool": "rwa.read", "cards": cards}


def run_rwa_read(args: dict[str, str] | None = None) -> dict:
    args = args or {}
    return execute(symbol=args.get("symbol") or None, chain=args.get("chain") or None)
