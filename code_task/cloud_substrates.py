"""8515 Cloud bypass lane registry — GLM / DeepSeek (Ollama cloud)."""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

# Cloud tab multi-turn: auto-cap long turns (cloud_memory_scope).
# Do NOT use glm52/kimi/deepseek input_scope builders here — they hard-reject >8000
# and break real store history (empty_content → 502).
from code_task.cloud_memory_scope import (
    build_deepseek_cloud_memory_messages,
    build_glm52_cloud_memory_messages,
    build_glm53_cloud_memory_messages,
    build_glm53_full_cloud_memory_messages,
)

BuildFn = Callable[[list[dict[str, Any]]], list[dict[str, str]]]

DEFAULT_GLM_MODEL = os.environ.get("WORKBENCH_GLM_MODEL", "glm-5.2:cloud").strip()
DEFAULT_KIMI_MODEL = os.environ.get("WORKBENCH_KIMI_MODEL", "kimi-k2.6:cloud").strip()
DEFAULT_DEEPSEEK_MODEL = os.environ.get("WORKBENCH_DEEPSEEK_MODEL", "deepseek-v4-pro:cloud").strip()
DEFAULT_GLM53_MODEL = os.environ.get("WORKBENCH_GLM53_MODEL", "glm-5.3-flash:cloud").strip()
DEFAULT_GLM53_FULL_MODEL = os.environ.get("WORKBENCH_GLM53_FULL_MODEL", "glm-5.3:cloud").strip()

CLOUD_SUBSTRATES: dict[str, dict[str, Any]] = {
    "glm52": {
        "label": "GLM 5.2",
        "default_model": DEFAULT_GLM_MODEL,
        "build_messages": build_glm52_cloud_memory_messages,
        "think": True,
    },
    "deepseek_v4": {
        "label": "DeepSeek V4",
        "default_model": DEFAULT_DEEPSEEK_MODEL,
        "build_messages": build_deepseek_cloud_memory_messages,
        "think": False,  # 与 scout / cloud_attempt_plan 同规
    },
    "glm53": {
        "label": "GLM 5.3 Flash",
        "default_model": DEFAULT_GLM53_MODEL,
        "build_messages": build_glm53_cloud_memory_messages,
        "think": True,  # 5.3 强制 think:false 会把 CoT 写进 content
    },
    "glm53_full": {
        "label": "GLM 5.3",
        "default_model": DEFAULT_GLM53_FULL_MODEL,
        "build_messages": build_glm53_full_cloud_memory_messages,
        "think": True,  # 与 Flash 同:think 通道黑盒,禁止 no_think 漏 CoT
    },
}


def resolve_substrate(raw: str | None) -> str:
    key = (raw or "glm52").strip().lower()
    if key in ("kimi_k3", "kimi-k3", "kimi_k3_cloud"):
        key = "glm53"
    if key in ("glm53_flash_cloud", "glm-5.3-flash", "glm53_flash"):
        key = "glm53"
    if key in (
        "minimax",
        "minimax_cloud",
        "minimax_m3",
        "glm53_full_cloud",
        "glm-5.3",
        "glm53_full",
    ):
        key = "glm53_full"
    if key in CLOUD_SUBSTRATES:
        return key
    raise ValueError(
        f"unknown substrate: {raw!r} (expected glm52|deepseek_v4|glm53|glm53_full)"
    )
