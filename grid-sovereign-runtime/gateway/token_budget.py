"""Per-route token budgets + thinking payload (gateway only)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

ROUTE_KEYS = ("compile", "chat", "gateway", "task")

DEFAULT_BUDGET = {
    "compile_max_tokens": 256,
    "chat_max_tokens": 400,
    "gateway_max_tokens": 1024,
    "task_max_tokens": 4096,
    "thinking_cap": 128,
}


def merge_aster_budget(cfg: dict, demo_root: Path) -> dict:
    """Overlay [budget] from config/aster.toml when present."""
    aster_path = demo_root / "config" / "aster.toml"
    if not aster_path.is_file():
        return cfg
    try:
        import tomllib

        data = tomllib.loads(aster_path.read_text(encoding="utf-8"))
    except Exception:
        return cfg
    budget = data.get("budget") or {}
    if not isinstance(budget, dict):
        return cfg
    out = dict(cfg)
    mapping = {
        "compile_max_tokens": "compile_max_tokens",
        "chat_max_tokens": "chat_max_tokens",
        "gateway_max_tokens": "gateway_max_tokens",
        "task_max_tokens": "task_max_tokens",
        "thinking_cap": "thinking_cap",
    }
    for src, dst in mapping.items():
        if budget.get(src) is not None:
            out[dst] = budget[src]
    if budget.get("thinking_cap") is not None:
        out["max_reasoning_tokens"] = budget["thinking_cap"]
    ls = data.get("lm_studio") or {}
    if isinstance(ls, dict) and ls.get("vl_model_id"):
        out["vl_model"] = str(ls["vl_model_id"]).strip()
    return out


def route_default_max_tokens(route: str, config: dict) -> int:
    route = route if route in ROUTE_KEYS else "chat"
    key = f"{route}_max_tokens"
    if key in config:
        return int(config[key])
    return int(config.get("chat_max_tokens", DEFAULT_BUDGET["chat_max_tokens"]))


def resolve_max_tokens(route: str, client_max: int | None, config: dict) -> int:
    """8501 owns route budgets; client may set a lower ceiling (never raise above config)."""
    cap = route_default_max_tokens(route, config)
    if client_max is not None:
        try:
            return min(cap, max(1, int(client_max)))
        except (TypeError, ValueError):
            pass
    return cap


def resolve_chat_route(body: dict) -> str:
    """tools present → task (4096); else chat (400)."""
    if body.get("tools"):
        return "task"
    return "chat"


def thinking_cap(config: dict) -> int | None:
    if config.get("thinking_cap") is not None:
        return int(config["thinking_cap"])
    if config.get("max_reasoning_tokens") is not None:
        return int(config["max_reasoning_tokens"])
    return None


def openai_thinking_payload(config: dict) -> dict[str, Any]:
    """Tier (a) template kwargs + (b) reasoning cap; (c) telemetry if unsupported."""
    extra: dict[str, Any] = {
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    cap = thinking_cap(config)
    if cap is not None:
        extra["max_reasoning_tokens"] = cap
    return extra
