"""Provider routing: explicit override (body/X-Provider), default by endpoint, failover."""
import os
from typing import Any, Optional

from app.config import (
    ALLOWED_PROVIDERS,
    DEFAULT_CHAT_PROVIDER,
    DEFAULT_TTS_PROVIDER,
    DEFAULT_VISION_PROVIDER,
)
from app.models import ModeEnum, ProviderEnum, TaskTypeEnum

# Lazy imports to avoid circular deps and optional deps
_providers_cache: dict[str, Any] = {}


def _get_mock_chat():
    from app.providers.mock import MockChatProvider
    return MockChatProvider()


def _get_mock_tts():
    from app.providers.mock import MockTTSProvider
    return MockTTSProvider()


def _get_mock_vision():
    from app.providers.mock import MockVisionProvider
    return MockVisionProvider()


def _get_claude_chat():
    from app.providers.claude import ClaudeProvider
    return ClaudeProvider()


def _get_openai_chat():
    from app.providers.openai import OpenAIProvider
    return OpenAIProvider()


def _get_gemini_vision():
    from app.providers.gemini import GeminiProvider
    return GeminiProvider()


def resolve_provider(
    explicit: Optional[str],
    header_provider: Optional[str],
) -> Optional[str]:
    """Resolve provider name from body.provider or X-Provider header. Returns None if no override."""
    for raw in (explicit, header_provider):
        if not raw:
            continue
        name = str(raw).strip().lower()
        if name in ALLOWED_PROVIDERS:
            return name
    return None


# Default routing
def default_chat_provider(mode: Optional[ModeEnum], task_type: Optional[TaskTypeEnum]) -> str:
    if mode == ModeEnum.compile:
        return "openai"
    if task_type in (TaskTypeEnum.spec, TaskTypeEnum.contract, TaskTypeEnum.code):
        return "openai"
    return DEFAULT_CHAT_PROVIDER if DEFAULT_CHAT_PROVIDER in ALLOWED_PROVIDERS else "claude"


def default_vision_provider() -> str:
    return DEFAULT_VISION_PROVIDER if DEFAULT_VISION_PROVIDER in ALLOWED_PROVIDERS else "gemini"


def default_tts_provider() -> str:
    return DEFAULT_TTS_PROVIDER if DEFAULT_TTS_PROVIDER in ALLOWED_PROVIDERS else "mock"


# Chat: chain claude -> openai -> mock
CHAT_FALLBACK_CHAIN = ["claude", "openai", "mock"]


def select_chat_provider(
    body_provider: Optional[ProviderEnum],
    header_provider: Optional[str],
    mode: Optional[ModeEnum],
    task_type: Optional[TaskTypeEnum],
) -> tuple[str, list[str]]:
    """Returns (selected_provider_name, full_chain_for_failover)."""
    explicit = resolve_provider(
        body_provider.value if body_provider else None,
        header_provider,
    )
    if explicit:
        chain = [explicit]
        for p in CHAT_FALLBACK_CHAIN:
            if p not in chain:
                chain.append(p)
        return explicit, chain
    default = default_chat_provider(mode, task_type)
    chain = [default]
    for p in CHAT_FALLBACK_CHAIN:
        if p not in chain:
            chain.append(p)
    return default, chain


def select_vision_provider(
    body_provider: Optional[ProviderEnum],
    header_provider: Optional[str],
) -> tuple[str, list[str]]:
    explicit = resolve_provider(
        body_provider.value if body_provider else None,
        header_provider,
    )
    if explicit:
        chain = [explicit, "mock"]
        return explicit, list(dict.fromkeys(chain))
    default = default_vision_provider()
    return default, [default, "mock"]


def select_tts_provider(
    body_provider: Optional[ProviderEnum],
    header_provider: Optional[str],
) -> tuple[str, list[str]]:
    explicit = resolve_provider(
        body_provider.value if body_provider else None,
        header_provider,
    )
    if explicit:
        chain = [explicit, "mock"]
        return explicit, list(dict.fromkeys(chain))
    default = default_tts_provider()
    return default, [default, "mock"]


def get_chat_provider(name: str):
    if name == "mock":
        return _get_mock_chat()
    if name == "claude":
        return _get_claude_chat()
    if name == "openai":
        return _get_openai_chat()
    return _get_mock_chat()


def get_vision_provider(name: str):
    if name == "mock":
        return _get_mock_vision()
    if name == "gemini":
        return _get_gemini_vision()
    return _get_mock_vision()


def get_tts_provider(name: str):
    if name == "mock":
        return _get_mock_tts()
    return _get_mock_tts()
