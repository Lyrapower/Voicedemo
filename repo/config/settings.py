from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _aster_lm_defaults() -> tuple[str, str, float, int]:
    try:
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from models.aster_config import (
            lm_studio_api_model,
            lm_studio_base,
            lm_studio_max_tokens,
            lm_studio_temperature,
        )

        return (
            lm_studio_base(),
            lm_studio_api_model(),
            lm_studio_temperature(),
            lm_studio_max_tokens(),
        )
    except Exception:
        return "http://127.0.0.1:1234/v1", "qwen2.5-1.5b", 0.3, 512


_ASTER_BASE, _ASTER_MODEL, _ASTER_TEMP, _ASTER_MAX_TOKENS = _aster_lm_defaults()


@dataclass(frozen=True)
class Settings:
    substrate_backend: str = os.environ.get("SUBSTRATE_BACKEND", "lmstudio")
    lm_studio_base_url: str = os.environ.get("LM_STUDIO_BASE_URL", _ASTER_BASE)
    lm_studio_model: str = os.environ.get("LM_STUDIO_MODEL", _ASTER_MODEL)
    ollama_base_url: str = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "compile_layer")
    llama_cpp_base_url: str = os.environ.get("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080")

    connect_timeout_s: float = float(os.environ.get("LLM_CONNECT_TIMEOUT_S", "5"))
    read_timeout_s: float = float(os.environ.get("LLM_READ_TIMEOUT_S", "120"))

    temperature: float = float(os.environ.get("LLM_TEMPERATURE", str(_ASTER_TEMP)))
    top_p: float = float(os.environ.get("LLM_TOP_P", "0.9"))
    repeat_penalty: float = float(os.environ.get("LLM_REPEAT_PENALTY", "1.1"))
    num_ctx: int = int(os.environ.get("LLM_NUM_CTX", "2048"))
    num_predict: int = int(os.environ.get("LLM_NUM_PREDICT", str(_ASTER_MAX_TOKENS)))
    num_thread: int = int(os.environ.get("LLM_NUM_THREAD", "2"))


settings = Settings()
