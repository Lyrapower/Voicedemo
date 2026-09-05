"""Chain isolation guards — Grid must never see Sonnet output in its request."""
from __future__ import annotations

FORBIDDEN_IN_GRID_PROMPT = (
    "aether_premarket_sonnet",
    "aether_premarket_deepseek",
    "journal_sonnet",
    "journal_deepseek",
    "SONNET lane",
    "DEEPSEEK V4",
    "云端·SONNET",
    "premarket_sonnet",
    "premarket_deepseek",
)


def assert_grid_prompt_isolated(prompt: str) -> None:
    low = (prompt or "").lower()
    for token in FORBIDDEN_IN_GRID_PROMPT:
        if token.lower() in low:
            raise ValueError(f"grid prompt isolation violation: contains {token!r}")


FORBIDDEN_SONNET_TOOLS = (
    "web_search",
    "web_fetch",
    "brave_search",
    "google_search",
    "news",
    "retrieval",
    "browse",
    "mcp_",
)


def assert_sonnet_no_retrieval_tools(*, system_prompt: str = "", tools: list | None = None) -> None:
    """Sonnet premarket lane must not attach retrieval/news tools at runtime."""
    low = (system_prompt or "").lower()
    for token in FORBIDDEN_SONNET_TOOLS:
        if token in low:
            raise ValueError(f"sonnet runtime isolation: forbidden token in system prompt: {token!r}")
    for tool in tools or []:
        name = ""
        if isinstance(tool, dict):
            fn = tool.get("function") or {}
            name = str(fn.get("name") or tool.get("name") or "")
        else:
            name = str(tool)
        lname = name.lower()
        for token in FORBIDDEN_SONNET_TOOLS:
            if token in lname:
                raise ValueError(f"sonnet runtime isolation: forbidden tool {name!r}")


def assert_sonnet_prompt_isolated(prompt: str) -> None:
    low = (prompt or "").lower()
    for token in ("aether_premarket_grid", "journal_grid", "GRID lane", "本地·GRID"):
        if token.lower() in low:
            raise ValueError(f"sonnet prompt isolation violation: contains {token!r}")
