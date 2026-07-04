"""Load active Aster config from config/aster.toml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPO_ROOT / "config" / "aster.toml"


def _parse_toml(text: str) -> dict[str, Any]:
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        import tomli

        return tomli.loads(text)


@lru_cache(maxsize=1)
def load_aster_config() -> dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return {}
    return _parse_toml(_CONFIG_PATH.read_text(encoding="utf-8"))


def repo_root() -> Path:
    return _REPO_ROOT


def section(name: str) -> dict[str, Any]:
    val = load_aster_config().get(name, {})
    return val if isinstance(val, dict) else {}


def budget_section() -> dict[str, Any]:
    b = section("budget")
    if b:
        return b
    ls = section("lm_studio")
    return {
        "compile_max_tokens": ls.get("compile_max_tokens", 256),
        "chat_max_tokens": ls.get("chat_max_tokens", ls.get("max_tokens", 400)),
        "gateway_max_tokens": ls.get("gateway_max_tokens", 1024),
        "task_max_tokens": ls.get("task_max_tokens", 4096),
        "thinking_cap": ls.get("max_reasoning_tokens", ls.get("thinking_cap", 128)),
    }


def lm_studio_api_model() -> str:
    ls = section("lm_studio")
    return str(ls.get("api_model_id") or ls.get("compile_model", "qwen2.5-1.5b"))


def lm_studio_hf_model() -> str:
    ls = section("lm_studio")
    return str(ls.get("compile_model_hf") or "mlx-community/Qwen2.5-1.5B-4bit")


def lm_studio_temperature() -> float:
    ls = section("lm_studio")
    if "temperature" in ls:
        return float(ls["temperature"])
    return 0.3


def lm_studio_max_tokens() -> int:
    b = budget_section()
    return int(b.get("chat_max_tokens", 400))


def lm_studio_compile_max_tokens() -> int:
    return int(budget_section().get("compile_max_tokens", 256))


def lm_studio_chat_max_tokens() -> int:
    return int(budget_section().get("chat_max_tokens", 400))


def lm_studio_gateway_max_tokens() -> int:
    return int(budget_section().get("gateway_max_tokens", 1024))


def lm_studio_task_max_tokens() -> int:
    return int(budget_section().get("task_max_tokens", 4096))


def lm_studio_max_reasoning_tokens() -> int | None:
    cap = budget_section().get("thinking_cap")
    if cap is not None:
        return int(cap)
    return None


def lm_studio_context_length() -> int:
    ls = section("lm_studio")
    return int(ls.get("context_length", 8192))


def lm_studio_repeat_penalty() -> float:
    ls = section("lm_studio")
    return float(ls.get("repeat_penalty", 1.35))


def build_lm_studio_system_prompt() -> str:
    """LM Studio Aster tab chat identity (compile contract stays on :8501 /compile)."""
    ls = section("lm_studio")
    explicit = ls.get("system_prompt")
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    rel = ls.get("system_prompt_file")
    if rel:
        p = _REPO_ROOT / str(rel)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return ""


def lm_studio_virtual_model_id() -> str:
    return str(section("lm_studio").get("virtual_model_id") or "demo/aster")


def gateway_endpoint() -> str:
    routing = load_aster_config().get("routing") or {}
    return str(routing.get("gateway_endpoint") or "http://127.0.0.1:8501").rstrip("/")


def direct_1234_allowed() -> bool:
    routing = load_aster_config().get("routing") or {}
    return bool(routing.get("direct_1234_allowed", False))


def lm_studio_tab_system_prompt() -> str:
    return build_lm_studio_system_prompt()


def lm_studio_system_prompt() -> str:
    return build_lm_studio_system_prompt()


def channel_host() -> str:
    return str(section("channel").get("host", "127.0.0.1"))


def compile_model_id() -> str:
    return lm_studio_api_model()


def lm_studio_base() -> str:
    return str(section("lm_studio").get("api_base", "http://127.0.0.1:1234/v1"))


def lm_studio_gateway_base() -> str:
    ls = section("lm_studio")
    gw = ls.get("gateway_api_base")
    if gw:
        return str(gw).rstrip("/")
    return f"{gateway_endpoint()}/v1"


def resolve_lm_studio_base() -> str:
    """When direct_1234_allowed is false, programmatic clients use :8501 gateway."""
    if direct_1234_allowed():
        return lm_studio_base().rstrip("/")
    return lm_studio_gateway_base().rstrip("/")


def lm_studio_gateway_plugin() -> str:
    return str(section("lm_studio").get("gateway_plugin", "demo/aster"))


def channel_port() -> int:
    return int(section("channel").get("port", 8787))


def database_path() -> Path:
    rel = str(section("state_persistence").get("database_path", "local_router.db"))
    p = Path(rel)
    return p if p.is_absolute() else _REPO_ROOT / p


def inject_system_prompt() -> bool:
    return bool(section("runtime").get("inject_system_prompt", False))


def load_reference_docs() -> bool:
    return bool(section("runtime").get("load_reference_docs", False))


def semantic_output_channels() -> dict[str, Any]:
    return section("semantic_mapping").get("output_channels", {})


def require_both_output_channels() -> bool:
    return bool(semantic_output_channels().get("require_both", False))


def sandbox_compiler_mode() -> str:
    return str(section("sandbox").get("compiler_mode", "ast_only"))
