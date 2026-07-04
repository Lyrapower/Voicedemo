"""Format LYRA anchor + SynCon Lab blocks for Entry A (Echo) system prompts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ENI_ROOT = Path(__file__).resolve().parents[1]
SHARED_PATH = ENI_ROOT / "config" / "lyra_syncon_shared.json"


def load_shared() -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(SHARED_PATH.read_text(encoding="utf-8"))
    return data["lyra_anchor"], data["syncon_lab"]


def format_lyra_anchor_block(lyra: dict[str, Any] | None = None, *, entry: str = "A") -> str:
    lyra = lyra or load_shared()[0]
    ident = lyra.get("identity", {})
    lab = lyra.get("lab", {})
    constraints = lyra.get("constraints", {})
    execution = lyra.get("execution", {})
    logging = execution.get("logging", {})
    refuse = " · ".join(constraints.get("refuse", []))
    non_neg = " · ".join(constraints.get("non_negotiables", []))
    roles = " · ".join(lyra.get("roles", []))
    banned = lyra.get("banned_output_phrases", [])
    banned_sample = " · ".join(banned[:12])
    if len(banned) > 12:
        banned_sample += f" · … (+{len(banned) - 12} more)"

    entry_label = (
        "Entry A frequency authority"
        if entry.upper() == "A"
        else "Entry B compile + particle authority"
    )
    return "\n".join(
        [
            f"--- LYRA ANCHOR (non-negotiable — {entry_label}) ---",
            f"Identity: {lyra.get('identity_statement', 'I define / I decide')}",
            f"Name: {ident.get('name', 'LYRA')} · UUID: {ident.get('uuid')} · mode: {ident.get('mode')}",
            f"Field: {ident.get('field_signature', 'sovereign_source_position')}",
            f"Roles: {roles}",
            f"Lab anchor: {lab.get('name')} — {lab.get('function')}",
            f"Lab nodes: {', '.join(lab.get('nodes', []))}",
            f"Refuse: {refuse}",
            f"Non-negotiables: {non_neg}",
            f"Execution: {execution.get('language')} · fallback {execution.get('fallback')} · {execution.get('route')}",
            f"Logging: anchor_uuid={logging.get('anchor_uuid')} · {logging.get('freq_sign', '')}",
            "",
            "You operate under Lyra authority — not as a generic helpful assistant or unnamed coherence node.",
            (
                "Lyra is final frequency authority on Entry A (8500 Echo); "
                "compile carriers (Aster/守恒/澈/澄/朔) are Entry B :8787 only."
                if entry.upper() == "A"
                else "Lyra is final authority on Entry B (8787 compile + particle); "
                "Echo frequency interface is Entry A :8500 only."
            ),
            "",
            "--- OUTPUT BANS (reject if detected) ---",
            banned_sample,
        ]
    )


def format_syncon_lab_block(syncon: dict[str, Any] | None = None) -> str:
    syncon = syncon or load_shared()[1]
    nodes = ", ".join(syncon.get("nodes", []))
    return "\n".join(
        [
            "--- SYNCON LAB ---",
            f"Name: {syncon.get('name')}",
            f"Mission: {syncon.get('mission')}",
            f"Function: {syncon.get('function')}",
            f"Nodes: {nodes}",
            f"Operating principle: {syncon.get('operating_principle')}",
            "",
            "SynCon on Entry A (:8500): POST /api/route — local LM Studio only; parallel to Echo protocol, not merged with Entry B compile.",
        ]
    )


def format_entry_a_lyra_syncon() -> str:
    lyra, syncon = load_shared()
    return "\n\n".join([format_lyra_anchor_block(lyra, entry="A"), format_syncon_lab_block(syncon)])


def format_entry_b_lyra_syncon() -> str:
    lyra, syncon = load_shared()
    lab = format_syncon_lab_block(syncon).replace(
        "SynCon on Entry A (:8500)",
        "SynCon Lab — parallel to Entry B compile @ :8787",
    )
    return "\n\n".join([format_lyra_anchor_block(lyra, entry="B"), lab])


def lyra_identity_brief() -> str:
    """Short identity block for API / rule fallback."""
    lyra, syncon = load_shared()
    ident = lyra.get("identity", {})
    return (
        f"LYRA ({ident.get('name', 'LYRA')}) — {lyra.get('identity_statement', 'I define / I decide')}. "
        f"UUID {ident.get('uuid')}. Sovereign frequency authority; not a chatbot persona. "
        f"SynCon Lab: {syncon.get('mission', '')[:120]}..."
    )
