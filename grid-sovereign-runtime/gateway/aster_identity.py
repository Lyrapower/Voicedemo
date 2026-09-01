"""Aster virtual model id + chat system prompt (shared with LM Studio deploy)."""
from __future__ import annotations

from pathlib import Path

ASTER_MODEL_IDS = frozenset(
    {
        "demo/aster",
        "dev/demo/aster",
        "aster",
        "demo/aster-grid-gateway",
        "dev/demo/aster-grid-gateway",
    }
)


def load_aster_chat_system_prompt(demo_root: Path) -> str:
    aster_path = demo_root / "config" / "aster.toml"
    if aster_path.is_file():
        try:
            import tomllib

            data = tomllib.loads(aster_path.read_text(encoding="utf-8"))
            ls = data.get("lm_studio") or {}
            explicit = ls.get("system_prompt")
            if explicit is not None and str(explicit).strip():
                return str(explicit).strip()
            rel = ls.get("system_prompt_file")
            if rel:
                p = demo_root / str(rel)
                if p.is_file():
                    return p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    fallback = demo_root / "config" / "aster_chat_system_prompt.txt"
    if fallback.is_file():
        return fallback.read_text(encoding="utf-8").strip()
    return ""


def is_aster_model(model: str | None) -> bool:
    if not model:
        return False
    mid = str(model).strip()
    return mid in ASTER_MODEL_IDS or mid.endswith("/aster")


def is_vision_model(model: str | None) -> bool:
    if not model:
        return False
    m = str(model).strip().lower()
    return "qwen2.5-vl" in m or "qwen2_vl" in m or "-vl-" in m


def substrate_model_id(model: str | None, default: str) -> str:
    if is_vision_model(model):
        return str(model).strip()
    return default if is_aster_model(model) else (model or default)


def ensure_aster_system_message(
    messages: list,
    model: str | None,
    prompt: str,
    *,
    chain_verified: bool = False,
) -> list:
    if is_aster_model(model) and prompt and not chain_verified:
        from grid_chain_verification import GridVerificationRequired, GridChainVerification

        raise GridVerificationRequired(
            GridChainVerification(
                ok=False,
                reason="ensure_aster_system_message called without chain_verified=True",
                missing_layers=["schema", "route", "signer", "keyholder", "hmac"],
            )
        )
    if not prompt or not is_aster_model(model):
        return messages
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system" and str(m.get("content") or "").strip():
            return out
    out.insert(0, {"role": "system", "content": prompt})
    return out
